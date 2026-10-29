"""What a Lease owes at signing, the draft's Security Deposit and the Initial Rent Invoice.

V1-060 B6, DL-100 (owner 27/10/2026): a walk-in draft Lease carries the Security Deposit the
customer will pay, so its printed draft shows it; Sign Lease first receives the full money due at
signing (the rest of the Security Deposit and the Initial Rent Invoice), signs, then makes the
Initial Rent Invoice at once so the money just received pays it. The amounts come from
app.lease_signing_preview (migration 20270325_244), which reads the Invoice generator's own rules;
the Invoice is made by app.generate_rent_service_invoice, as billing makes every Rent Invoice.

DL-101 (owner 27/10/2026, migration 20270326_245): the Security Deposit amount is a Lease term like
the Rent, so a draft from a Reservation records it too, starting at the Reservation's amount and
never below the money already received. Sign Lease applies it to the Reservation's Security Deposit
right after signing (app.apply_lease_planned_security_deposit), then receives the rest.

DL-108 (V1-060 B7, migration 20270330_249): Sign Lease is one command in one database transaction,
app.sign_lease_with_payment: the Payment and its Receipt, the signatures, the signing, the draft's
Security Deposit, the Initial Rent Invoice, the money paying that Invoice by name and the rest
going into the Security Deposit are all saved, or nothing is. The separate Initial Rent Invoice and
apply routes of DL-100 and DL-101 are gone; their database functions are steps of the command.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final, NoReturn, Protocol, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from psycopg import IsolationLevel
from psycopg.types.json import Jsonb, set_json_loads
from pydantic import BaseModel, ConfigDict, Field

from property_rental.api_refusals import Refusal, RefusedRequest
from property_rental.browser_security import require_browser_mutation
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import Evidence, Identity, Instant, Memo, StrictInput, UsdAmount
from property_rental.payment_confirmation import _exact_json
from property_rental.settings import Settings

LEASE_READ_CAPABILITY: Final = "leases.read"
LEASE_DRAFT_CAPABILITY: Final = "leases.draft"
LEASE_SIGN_CAPABILITY: Final = "leases.sign"
# DL-108: Sign Lease receives the money and puts it where it belongs in the same command.
PAYMENT_RECORD_CAPABILITY: Final = "payments.record"
PAYMENT_ALLOCATE_CAPABILITY: Final = "payments.allocate"
DEPOSIT_MANAGE_CAPABILITY: Final = "deposits.manage"
# DL-101: the Reservation's Security Deposit in the preview shows only to a person who may see
# deposits or Bookings.
DEPOSIT_READ_CAPABILITY: Final = "deposits.read"
RESERVATION_READ_CAPABILITY: Final = "reservations.read"
CONNECT_TIMEOUT_SECONDS: Final = 3
LOCK_TIMEOUT_MS: Final = 3_000
QUERY_TIMEOUT_MS: Final = 5_000
# The one-step signing does the work of seven commands in one statement.
SIGN_QUERY_TIMEOUT_MS: Final = 15_000
MAX_CENTS: Final = 9_000_000_000_000_000

# The database's own refusal texts, answered with a plain message the screen shows.
REFUSALS: Final[dict[str, Refusal]] = {
    "Only a drafted Lease takes a planned Security Deposit": Refusal(
        409,
        "PLANNED_DEPOSIT_NOT_DRAFT",
        "Only a draft Lease takes a planned Security Deposit.",
    ),
    "The Security Deposit cannot be less than the money already received": Refusal(
        409,
        "PLANNED_DEPOSIT_BELOW_RECEIVED",
        "The Security Deposit cannot be less than the money already received.",
        ("BR-DEP-004",),
    ),
    "Sign the Lease before its Security Deposit changes": Refusal(
        409, "PLANNED_DEPOSIT_NOT_SIGNED", "Sign the Lease first."
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
    "This Security Deposit save was already used for another amount": Refusal(
        409,
        "PLANNED_DEPOSIT_SAVE_REUSED",
        "This save was already used for another amount. Close the form and save again.",
    ),
}
PARTIAL_SERVICE = Refusal(
    409,
    "INITIAL_RENT_SERVICE_PART_MONTH",
    "A Service on this Lease covers only part of a month or has no rate. "
    "Fix the Service dates or its rate first.",
    ("BR-SVC-012",),
)
# V1-060 B7 (second and third review): the way the money came was switched off after the dialog
# opened, or its record or the Customer's is not there.
SIGNING_PAYMENT_SOURCE_GONE: Final = Refusal(
    409,
    "SIGNING_PAYMENT_SOURCE_GONE",
    "The way the money came is switched off, or the Customer was not found. Nothing was saved. "
    "Close, open Sign Lease again and choose how the money came.",
)
# DL-108: why Sign Lease saved nothing, in words the dialog shows.
SIGN_REFUSALS: Final[dict[str, Refusal]] = {
    **REFUSALS,
    "Only a drafted Lease may be signed": Refusal(
        409, "SIGNING_NOT_DRAFT", "This Lease is no longer a draft. Nothing was saved."
    ),
    "Every Lease signer, including the Primary Tenant, must sign": Refusal(
        409,
        "SIGNING_SIGNERS_CHANGED",
        "Every Signer must sign, and the Signers changed meanwhile. Nothing was saved. "
        "Close, open Sign Lease again and tick every Signer.",
    ),
    "Lease terms are incomplete": Refusal(
        409,
        "SIGNING_TERMS_INCOMPLETE",
        "Add the Start Date, the End Date and the Rent first (Edit draft). Nothing was saved.",
    ),
    "Lease End Date must be the last day of a calendar month": Refusal(
        409,
        "SIGNING_END_DATE_NOT_MONTH_END",
        "The End Date must be the last day of a month. Change it with Edit draft. "
        "Nothing was saved.",
    ),
    "Record the Security Deposit on the draft first": Refusal(
        409,
        "SIGNING_DEPOSIT_MISSING",
        "This draft has no Security Deposit yet. Add it with Edit draft first. Nothing was saved.",
        ("BR-DEP-002",),
    ),
    "A walk-in Lease's Security Deposit needs deposits.manage": Refusal(
        403,
        "SIGNING_NO_DEPOSIT_RIGHT",
        "A walk-in Lease's Security Deposit needs the right to manage deposits. Ask the Owner. "
        "Nothing was saved.",
    ),
    "The money due at signing changed": Refusal(
        409,
        "SIGNING_TOTAL_CHANGED",
        "The money due at signing changed meanwhile. Nothing was saved. "
        "Close and open Sign Lease again to see the new total.",
        ("BR-DEP-002",),
    ),
    "An Initial Rent Service covers only part of a month or has no rate": PARTIAL_SERVICE,
    "Unit has an open Occupancy": Refusal(
        409,
        "SIGNING_UNIT_OCCUPIED",
        "Someone still lives in this Parking (an open Occupancy). Nothing was saved.",
    ),
    "Unit cannot be occupied by this signing": Refusal(
        409,
        "SIGNING_UNIT_NOT_FREE",
        "This Parking cannot be signed now: it is Reserved for someone else, Out of Service or "
        "Occupied. Nothing was saved.",
    ),
    "Reservation cannot be completed by this signing": Refusal(
        409,
        "SIGNING_RESERVATION_ENDED",
        "The Customer's Reservation of this Parking has ended or changed, so this draft cannot "
        "take its Security Deposit. Nothing was saved. Ask the Owner or a Manager.",
    ),
    "The Reservation has no Security Deposit": Refusal(
        409,
        "SIGNING_RESERVATION_NO_DEPOSIT",
        "The Customer's Reservation of this Parking has no Security Deposit. Nothing was saved.",
    ),
    "The Deposit's Reservation is not active; this receipt is not recorded here": Refusal(
        409,
        "SIGNING_RESERVATION_ENDED",
        "The Customer's Reservation of this Parking has ended or changed, so this draft cannot "
        "take its Security Deposit. Nothing was saved. Ask the Owner or a Manager.",
    ),
    "Sign Lease key reused": Refusal(
        409,
        "SIGNING_KEY_REUSED",
        "This signing was already sent with other details. Nothing more was saved. "
        "Close and open Sign Lease again.",
    ),
    # V1-060 B7 (second and third review): refusals from a step inside the command.
    "Payment source not found": SIGNING_PAYMENT_SOURCE_GONE,
    "Payment Method is not accepted": SIGNING_PAYMENT_SOURCE_GONE,
}

# V1-060 B7 (second review): another signed Lease of the Unit covers these dates (the database's
# exclusion check), found before the Unit's own check. Other exclusion checks are SIGNING_REFUSED.
SIGNED_PERIOD_EXCLUSION: Final = "leases_signed_period_exclusive"
SIGNING_DATES_TAKEN: Final = Refusal(
    409,
    "SIGNING_DATES_TAKEN",
    "Another signed Lease of this Parking covers these dates. Nothing was saved. Check the dates "
    "with Edit draft, or ask the Owner.",
)


class LeaseSigningNotFound(LookupError):
    pass


class LeaseSigningUnavailable(RuntimeError):
    pass


class LeaseSigningInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SignWithPaymentCommand:
    """DL-108: the screen's one Sign Lease press: the Lease version it showed, the Signers it
    ticked and the money received (the Primary Tenant's own, in USD)."""

    idempotency_key: UUID
    expected_version: int
    signer_ids: tuple[UUID, ...]
    reason: str
    payment_method_id: UUID
    received_amount_minor: int
    received_at: datetime
    evidence_reference: str
    payer_intent_memo: str | None

    def request(self) -> dict[str, object]:
        """The Payment part as the database confirms it; the payer is the Lease's."""
        return {
            "payment_method_id": str(self.payment_method_id),
            "received_amount_minor": self.received_amount_minor,
            "received_at": self.received_at.astimezone(UTC).isoformat(),
            "evidence_reference": self.evidence_reference,
            "payer_intent_memo": self.payer_intent_memo,
            "channel_transaction_reference": None,
        }


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

    def sign_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: SignWithPaymentCommand,
        actor_id: UUID,
        may_create_deposit: bool,
    ) -> dict[str, object]: ...


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

    def sign_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: SignWithPaymentCommand,
        actor_id: UUID,
        may_create_deposit: bool,
    ) -> dict[str, object]:
        raise LeaseSigningUnavailable(str(lease_id))


def sign_with_payment_digest(
    property_id: UUID, lease_id: UUID, command: SignWithPaymentCommand
) -> str:
    """The whole request, so the same key with anything else is refused, never replayed."""
    payload = json.dumps(
        {
            "property_id": str(property_id),
            "lease_id": str(lease_id),
            "expected_version": command.expected_version,
            "signer_ids": sorted(str(signer) for signer in command.signer_ids),
            "reason": command.reason,
            "request": command.request(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
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
                    "SELECT app.lease_signing_preview(%s,%s) || jsonb_build_object("
                    "'held_security_deposit', app.lease_held_security_deposit(%s,%s))",
                    (property_id, lease_id, property_id, lease_id),
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

    def sign_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: SignWithPaymentCommand,
        actor_id: UUID,
        may_create_deposit: bool,
    ) -> dict[str, object]:
        if self._financial_database_url is None:
            raise LeaseSigningUnavailable
        digest = sign_with_payment_digest(property_id, lease_id, command)
        try:
            with self._connect(self._financial_database_url) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout',%s,true)",
                    (str(SIGN_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(
                    "SELECT app.sign_lease_with_payment(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        actor_id,
                        command.idempotency_key,
                        digest,
                        lease_id,
                        command.expected_version,
                        list(command.signer_ids),
                        command.reason,
                        Jsonb(command.request()),
                        may_create_deposit,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            _sign_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise LeaseSigningUnavailable
        return cast(dict[str, object], row[0])


class LeaseSigningConflict(RuntimeError):
    """The Lease changed after the screen read it (If-Match); nothing was saved."""


def _sign_error(exc: psycopg.Error) -> NoReturn:
    """DL-108: one refusal for the whole command; every failure saved nothing.

    V1-060 B7 (second review): an error the command raised is a refusal, because its transaction
    saved nothing and the same request fails the same way again. The command checks every deferred
    rule before it returns, so a rule broken at its end is raised by the command itself, never at
    the commit."""
    message = exc.diag.message_primary or ""
    sqlstate = exc.sqlstate or ""
    if sqlstate == "40001":
        raise LeaseSigningConflict from exc
    if message in SIGN_REFUSALS:
        raise RefusedRequest(SIGN_REFUSALS[message]) from exc
    if "Partial-month" in str(exc) or "rate is missing" in str(exc):
        raise RefusedRequest(PARTIAL_SERVICE) from exc
    if sqlstate in {"P0002", "P5301", "P4501"}:
        raise LeaseSigningNotFound from exc
    if sqlstate in {"P5302", "22023", "22P02", "22007", "22008"}:
        raise LeaseSigningInvalid from exc
    if sqlstate == "23P01" and exc.diag.constraint_name == SIGNED_PERIOD_EXCLUSION:
        raise RefusedRequest(SIGNING_DATES_TAKEN) from exc
    if sqlstate.startswith("23") or sqlstate in {"55000", "P4506", "P5S01", "P5305"}:
        raise RefusedRequest(SIGNING_REFUSED) from exc
    # Deadlock, lock, timeout and connection failures, and a failed commit, cannot prove that an
    # earlier try with this key did not commit: the screen sends the same request with the same
    # key again.
    raise LeaseSigningUnavailable from exc


SIGNING_REFUSED = Refusal(
    409,
    "SIGNING_REFUSED",
    "The Lease could not be signed with the records as they are now. Nothing was saved. "
    "Check the Lease, its Parking and its Customer, or ask the Owner.",
)


class PlannedDepositSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    plan_id: UUID = Field(strict=False)
    required_usd_cents: int = Field(ge=1, le=MAX_CENTS)
    reason: str = Field(min_length=1, max_length=500)


class SignPaymentSource(StrictInput):
    """The money received at signing: the Primary Tenant's own, in USD (DL-100)."""

    payment_method_id: Identity
    received_at: Instant
    evidence_reference: Evidence
    payer_intent_memo: Memo | None = None
    amount: UsdAmount


class SignWithPaymentSource(StrictInput):
    signer_ids: Annotated[list[Identity], Field(max_length=100)]
    reason: str = Field(strict=True, min_length=1, max_length=500)
    payment: SignPaymentSource


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


def _version(value: str | None) -> int:
    if value is None or not value.startswith('"') or not value.endswith('"'):
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED)
    try:
        parsed = int(value[1:-1])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
    if parsed < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return parsed


def _translate(exc: Exception) -> HTTPException | RefusedRequest:
    if isinstance(exc, (HTTPException, RefusedRequest)):
        return exc
    if isinstance(exc, LeaseSigningNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, LeaseSigningConflict):
        return HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
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
        if not any(
            is_authorized(
                actor, AuthorizationRequirement(capability=name, property_id=str(property_id))
            )
            for name in (DEPOSIT_READ_CAPABILITY, RESERVATION_READ_CAPABILITY)
        ):
            data = {**data, "held_security_deposit": None}
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

    @router.post("/leases/{lease_id}/sign-with-payment", status_code=status.HTTP_201_CREATED)
    def sign_with_payment(
        lease_id: UUID,
        source: SignWithPaymentSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """DL-108: the money, the signatures, the signing, the Initial Rent Invoice paid by name
        and the Security Deposit, saved together in one database transaction or not at all."""
        actor = _actor(request, resolver)
        for header in ("Idempotency-Key", "If-Match", "Origin", "X-CSRF-Token"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        try:
            property_id = flow.property_of(lease_id)
            for capability in (
                LEASE_SIGN_CAPABILITY,
                PAYMENT_RECORD_CAPABILITY,
                PAYMENT_ALLOCATE_CAPABILITY,
            ):
                _require(actor, property_id, capability)
            require_browser_mutation(request, settings)
            bind_financial_property(request, property_id)
            if idempotency_key.int == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
            command = SignWithPaymentCommand(
                idempotency_key=idempotency_key,
                expected_version=_version(if_match),
                signer_ids=tuple(source.signer_ids),
                reason=source.reason,
                payment_method_id=source.payment.payment_method_id,
                received_amount_minor=source.payment.amount.minor_units,
                received_at=source.payment.received_at,
                evidence_reference=source.payment.evidence_reference,
                payer_intent_memo=source.payment.payer_intent_memo,
            )
            if command.reason != command.reason.strip() or len(set(command.signer_ids)) != len(
                command.signer_ids
            ):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
            signed = flow.sign_with_payment(
                property_id,
                lease_id,
                command,
                _actor_id(actor),
                is_authorized(
                    actor,
                    AuthorizationRequirement(
                        capability=DEPOSIT_MANAGE_CAPABILITY, property_id=str(property_id)
                    ),
                ),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["ETag"] = f'"{signed["lease_version"]}"'
        return {"data": signed, "meta": financial_metadata(request)}

    return router
