"""Authorized Reservation resources and explicit lifecycle command routes."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Annotated, Final, Protocol, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
    DepositIdempotencyKeyReused,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    PostgresReservationService,
    ReservationAuthorizationError,
    ReservationCancelCommand,
    ReservationCommandConflictError,
    ReservationCommandInvalidError,
    ReservationCreateCommand,
    ReservationExtendCommand,
    ReservationLifecycleResult,
    ReservationNotFoundError,
    ReservationStatus,
    ReservationVersionConflictError,
    reservation_request_digest,
)
from property_rental.settings import Settings

RESERVATION_READ_CAPABILITY: Final = "reservations.read"
RESERVATION_CREATE_CAPABILITY: Final = "reservations.create"
RESERVATION_EXTEND_CAPABILITY: Final = "reservations.extend"
RESERVATION_CANCEL_CAPABILITY: Final = "reservations.cancel"
DEPOSIT_OVERRIDE_CAPABILITY: Final = "reservation_deposits.override"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100


class ReservationResourceNotFound(LookupError):
    """Reservation is absent or outside the authorized Property."""


class ReservationResourceUnavailable(RuntimeError):
    """Reservation persistence is unavailable."""


class ReservationResourceInvalid(ValueError):
    """Reservation input or cursor is invalid."""


@dataclass(frozen=True, slots=True)
class ReservationExtensionNotice:
    notice_id: UUID
    previous_expiration_date: date
    new_expiration_date: date
    approved_at: datetime
    reason_memo: str | None


@dataclass(frozen=True, slots=True)
class ReservationReceipt:
    receipt_id: UUID
    payment_id: UUID
    amount_usd_cents: int
    occurred_at: datetime
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class ReservationLifecycleEvidence:
    event_id: UUID
    event_kind: str
    reason_code: str
    responsibility: CancellationResponsibility
    reason_memo: str | None
    coordination_reference: str | None
    authorization_reference: str
    occurred_at: datetime
    business_date: date
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class ReservationDepositOutcomeEvidence:
    outcome_id: UUID
    outcome_kind: str
    amount_usd_cents: int
    source_lifecycle_event_id: UUID
    reason: str
    occurred_at: datetime
    actor_id: UUID
    authorization_reference: str


@dataclass(frozen=True, slots=True)
class ReservationResource:
    reservation_id: UUID
    property_id: UUID
    unit_id: UUID
    unit_number: str
    customer_id: UUID
    customer_name: str
    reservation_date: date
    original_expiration_date: date
    effective_expiration_date: date
    agreed_monthly_rent_usd_cents: int
    status: ReservationStatus
    version: int
    deposit_id: UUID
    deposit_required_usd_cents: int
    deposit_received_usd_cents: int
    deposit_outcome_state: DepositOutcomeState
    cancellation_reason_code: str | None
    cancellation_responsibility: CancellationResponsibility | None
    resulting_lease_id: UUID | None
    extension_notice: ReservationExtensionNotice | None
    extension_eligible: bool = False
    extension_days_remaining: int | None = None
    receipts: tuple[ReservationReceipt, ...] = ()
    lifecycle_events: tuple[ReservationLifecycleEvidence, ...] = ()
    deposit_outcomes: tuple[ReservationDepositOutcomeEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ReservationPage:
    items: tuple[ReservationResource, ...]
    next_cursor: str | None


class ReservationResourceFlow(Protocol):
    def list(
        self,
        property_id: UUID,
        *,
        reservation_status: ReservationStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ReservationPage: ...

    def get(self, reservation_id: UUID) -> ReservationResource: ...

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource: ...

    def extend(
        self,
        command: ReservationExtendCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource: ...

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource: ...

    def property_for_security_deposit_disposition(self, reservation_id: UUID) -> UUID: ...

    def create_security_deposit_disposition(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult: ...


class UnavailableReservationResourceFlow:
    def _raise(self) -> None:
        raise ReservationResourceUnavailable

    def list(
        self,
        property_id: UUID,
        *,
        reservation_status: ReservationStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ReservationPage:
        del property_id, reservation_status, limit, cursor
        self._raise()
        raise AssertionError

    def get(self, reservation_id: UUID) -> ReservationResource:
        del reservation_id
        self._raise()
        raise AssertionError

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del property_id, command, actor
        self._raise()
        raise AssertionError

    def extend(
        self,
        command: ReservationExtendCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del command, actor
        self._raise()
        raise AssertionError

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del command, actor
        self._raise()
        raise AssertionError

    def property_for_security_deposit_disposition(self, reservation_id: UUID) -> UUID:
        del reservation_id
        self._raise()
        raise AssertionError

    def create_security_deposit_disposition(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult:
        del command, actor
        self._raise()
        raise AssertionError


def _encode_cursor(reservation_date: date, reservation_id: UUID) -> str:
    raw = json.dumps([reservation_date.isoformat(), str(reservation_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[date, UUID] | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        return date.fromisoformat(str(decoded[0])), UUID(str(decoded[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ReservationResourceInvalid("cursor is invalid") from exc


class PostgresReservationResourceFlow:
    """Bounded Reservation queries and published lifecycle services."""

    _select: Final = """
        SELECT reservation.id, unit.property_id, reservation.unit_id, unit.unit_number,
               reservation.customer_id, customer.legal_name, reservation.reservation_date,
               reservation.original_expiration_date, reservation.effective_expiration_date,
               reservation.agreed_monthly_rent_usd_cents, reservation.status,
               reservation.version, deposit.id, deposit.required_usd_cents,
               COALESCE(sum(receipt.amount_usd_cents), 0)::bigint,
               CASE
                 WHEN (SELECT COALESCE(sum(refund.usd_accounting_value_cents
                              - COALESCE((SELECT sum(correction.source_balance_effect_usd_cents)
                                FROM app.refund_corrections AS correction
                                WHERE correction.refund_id=refund.id),0)),0)
                       FROM app.refunds AS refund WHERE refund.source_deposit_id=deposit.id) > 0
                   THEN 'REFUND'
                 WHEN EXISTS (SELECT 1 FROM app.deposit_dispositions AS disposition
                              WHERE disposition.deposit_id=deposit.id AND NOT EXISTS (
                                SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                                WHERE reversal.deposit_disposition_id=disposition.id))
                   THEN 'NON_REFUNDABLE_DISPOSITION'
                 ELSE 'PENDING_V1_031'
               END, reservation.cancellation_reason_code,
               reservation.cancellation_responsibility, reservation.resulting_lease_id,
               notice.id, notice.previous_expiration_date, notice.new_expiration_date,
               notice.approved_at, notice.reason_memo,
               (reservation.effective_expiration_date
                - timezone(property.timezone_name, clock_timestamp())::date) BETWEEN 0 AND 13,
               reservation.effective_expiration_date
                - timezone(property.timezone_name, clock_timestamp())::date
        FROM app.reservations AS reservation
        JOIN app.units AS unit ON unit.id = reservation.unit_id
        JOIN app.customers AS customer ON customer.id = reservation.customer_id
        JOIN app.properties AS property ON property.id = unit.property_id
        JOIN app.deposits AS deposit ON deposit.reservation_id = reservation.id
        LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
        LEFT JOIN app.reservation_extension_notices AS notice
          ON notice.reservation_id = reservation.id
    """
    _group: Final = """
        GROUP BY reservation.id, unit.property_id, unit.unit_number, customer.legal_name,
                 deposit.id, notice.id, property.timezone_name
    """

    def __init__(self, database_url: str, financial_database_url: str | None = None) -> None:
        self._database_url = database_url
        self._financial_database_url = financial_database_url

    @staticmethod
    def _resource(row: tuple[object, ...]) -> ReservationResource:
        notice = None
        if row[19] is not None:
            notice = ReservationExtensionNotice(
                UUID(str(row[19])),
                cast(date, row[20]),
                cast(date, row[21]),
                cast(datetime, row[22]),
                None if row[23] is None else str(row[23]),
            )
        responsibility = None if row[17] is None else CancellationResponsibility(str(row[17]))
        return ReservationResource(
            UUID(str(row[0])),
            UUID(str(row[1])),
            UUID(str(row[2])),
            str(row[3]),
            UUID(str(row[4])),
            str(row[5]),
            cast(date, row[6]),
            cast(date, row[7]),
            cast(date, row[8]),
            int(str(row[9])),
            ReservationStatus(str(row[10])),
            int(str(row[11])),
            UUID(str(row[12])),
            int(str(row[13])),
            int(str(row[14])),
            DepositOutcomeState(str(row[15])),
            None if row[16] is None else str(row[16]),
            responsibility,
            None if row[18] is None else UUID(str(row[18])),
            notice,
            bool(row[24]),
            int(str(row[25])),
        )

    def _fetch(self, query: str, parameters: tuple[object, ...]) -> list[tuple[object, ...]]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return list(connection.execute(query, parameters).fetchall())
        except psycopg.Error as exc:
            raise ReservationResourceUnavailable from exc

    def list(
        self,
        property_id: UUID,
        *,
        reservation_status: ReservationStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ReservationPage:
        decoded = _decode_cursor(cursor)
        clauses = ["unit.property_id = %s"]
        parameters: list[object] = [property_id]
        if reservation_status is not None:
            clauses.append("reservation.status = %s")
            parameters.append(reservation_status.value)
        if decoded is not None:
            clauses.append("(reservation.reservation_date, reservation.id) < (%s, %s)")
            parameters.extend(decoded)
        parameters.append(limit + 1)
        rows = self._fetch(
            self._select
            + " WHERE "
            + " AND ".join(clauses)
            + self._group
            + " ORDER BY reservation.reservation_date DESC, reservation.id DESC LIMIT %s",
            tuple(parameters),
        )
        resources = tuple(self._resource(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and resources:
            last = resources[-1]
            next_cursor = _encode_cursor(last.reservation_date, last.reservation_id)
        return ReservationPage(resources, next_cursor)

    def get(self, reservation_id: UUID) -> ReservationResource:
        rows = self._fetch(
            self._select + " WHERE reservation.id = %s" + self._group,
            (reservation_id,),
        )
        if not rows:
            raise ReservationResourceNotFound
        resource = self._resource(rows[0])
        try:
            with psycopg.connect(self._database_url) as connection:
                receipts = tuple(
                    ReservationReceipt(
                        UUID(str(row[0])),
                        UUID(str(row[1])),
                        int(str(row[2])),
                        cast(datetime, row[3]),
                        UUID(str(row[4])),
                    )
                    for row in connection.execute(
                        "SELECT id,payment_id,amount_usd_cents,occurred_at,actor_id "
                        "FROM app.deposit_receipts WHERE deposit_id=%s "
                        "ORDER BY occurred_at,id LIMIT 100",
                        (resource.deposit_id,),
                    ).fetchall()
                )
                lifecycle = tuple(
                    ReservationLifecycleEvidence(
                        UUID(str(row[0])),
                        str(row[1]),
                        str(row[2]),
                        CancellationResponsibility(str(row[3])),
                        None if row[4] is None else str(row[4]),
                        None if row[5] is None else str(row[5]),
                        str(row[6]),
                        cast(datetime, row[7]),
                        cast(date, row[8]),
                        UUID(str(row[9])),
                    )
                    for row in connection.execute(
                        "SELECT id,event_kind,cancellation_reason_code,"
                        "cancellation_responsibility,reason_memo,coordination_reference,"
                        "authorization_reference,occurred_at,business_date,actor_id "
                        "FROM app.reservation_lifecycle_events WHERE reservation_id=%s "
                        "ORDER BY occurred_at,id LIMIT 100",
                        (reservation_id,),
                    ).fetchall()
                )
                outcomes = tuple(
                    ReservationDepositOutcomeEvidence(
                        UUID(str(row[0])),
                        str(row[1]),
                        int(str(row[2])),
                        UUID(str(row[3])),
                        str(row[4]),
                        cast(datetime, row[5]),
                        UUID(str(row[6])),
                        str(row[7]),
                    )
                    for row in connection.execute(
                        "SELECT id,'DISPOSITION',amount_usd_cents,source_lifecycle_event_id,"
                        "reason,occurred_at,actor_id,authorization_reference "
                        "FROM app.deposit_dispositions WHERE governing_reservation_id=%s "
                        "UNION ALL "
                        "SELECT refund.id,'REFUND',refund.usd_accounting_value_cents,"
                        "refund.source_lifecycle_event_id,refund.reason,refund.processed_at,"
                        "refund.processed_by,refund.authorization_reference "
                        "FROM app.refunds AS refund "
                        "JOIN app.reservation_lifecycle_events AS event "
                        "ON event.id=refund.source_lifecycle_event_id "
                        "WHERE event.reservation_id=%s UNION ALL "
                        "SELECT reversal.id,'DISPOSITION_REVERSAL',disposition.amount_usd_cents,"
                        "disposition.source_lifecycle_event_id,reversal.reason,reversal.occurred_at,"
                        "reversal.actor_id,reversal.authorization_reference "
                        "FROM app.deposit_disposition_reversals AS reversal "
                        "JOIN app.deposit_dispositions AS disposition "
                        "ON disposition.id=reversal.deposit_disposition_id "
                        "WHERE disposition.governing_reservation_id=%s UNION ALL "
                        "SELECT correction.id,'REFUND_CORRECTION',"
                        "abs(correction.source_balance_effect_usd_cents),refund.source_lifecycle_event_id,"
                        "correction.reason,correction.occurred_at,correction.actor_id,"
                        "correction.authorization_reference "
                        "FROM app.refund_corrections AS correction "
                        "JOIN app.refunds AS refund ON refund.id=correction.refund_id "
                        "JOIN app.reservation_lifecycle_events AS event "
                        "ON event.id=refund.source_lifecycle_event_id "
                        "WHERE event.reservation_id=%s "
                        "ORDER BY 6,1 LIMIT 100",
                        (reservation_id, reservation_id, reservation_id, reservation_id),
                    ).fetchall()
                )
        except psycopg.Error as exc:
            raise ReservationResourceUnavailable from exc
        return replace(
            resource,
            receipts=receipts,
            lifecycle_events=lifecycle,
            deposit_outcomes=outcomes,
        )

    def _service(self, property_id: UUID, actor: AuthenticatedActor) -> PostgresReservationService:
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise ReservationAuthorizationError("Reservation actor is invalid") from exc
        return PostgresReservationService(
            self._database_url,
            property_id,
            actor_id,
            self._financial_database_url,
        )

    @staticmethod
    def _bound_disposition_query(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
            (str(DEPOSIT_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
            (str(DEPOSIT_QUERY_TIMEOUT_MS),),
        )

    def property_for_security_deposit_disposition(self, reservation_id: UUID) -> UUID:
        try:
            with psycopg.connect(
                self._database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_disposition_query(connection)
                row = connection.execute(
                    "SELECT unit.property_id FROM app.reservations AS reservation "
                    "JOIN app.units AS unit ON unit.id=reservation.unit_id "
                    "WHERE reservation.id=%s",
                    (reservation_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ReservationResourceUnavailable from exc
        if row is None:
            raise ReservationResourceNotFound
        return UUID(str(row[0]))

    def create_security_deposit_disposition(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult:
        property_id = self.property_for_security_deposit_disposition(command.reservation_id)
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise ReservationAuthorizationError("Reservation actor is invalid") from exc
        if not (
            _can(actor, property_id, RESERVATION_CANCEL_CAPABILITY)
            and _can(actor, property_id, "reservation_deposits.dispose")
        ):
            raise ReservationAuthorizationError("Reservation disposition is not authorized")
        if self._financial_database_url is None:
            raise ReservationAuthorizationError(
                "Dedicated Reservation financial persistence is unavailable"
            )
        try:
            with psycopg.connect(
                self._financial_database_url,
                connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                self._bound_disposition_query(connection)
                row = connection.execute(
                    "SELECT * FROM app.cancel_reservation_v2("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        command.idempotency_key,
                        reservation_request_digest("reservation.cancel", command),
                        command.event_id,
                        command.outcome_id,
                        command.refund_number,
                        command.reservation_id,
                        command.expected_version,
                        command.reason_code,
                        command.responsibility.value,
                        command.property_could_provide_unit,
                        command.reason_memo,
                        command.coordination_reference,
                        command.authorization_reference,
                        command.outcome_authorization_reference,
                        actor_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise ReservationNotFoundError("Reservation resource was not found") from exc
            if exc.sqlstate == "40001":
                raise ReservationVersionConflictError(
                    "Reservation version precondition was not met"
                ) from exc
            if exc.sqlstate == "P0001" and "idempotency key was reused" in str(exc).lower():
                raise DepositIdempotencyKeyReused("Reservation idempotency key was reused") from exc
            if exc.sqlstate in {"P0001", "23505"}:
                raise ReservationCommandConflictError("Reservation command conflicted") from exc
            if exc.sqlstate in {"22023", "23514", "55000"}:
                raise ReservationCommandInvalidError("Reservation command is invalid") from exc
            raise ReservationResourceUnavailable from exc
        if row is None:
            raise ReservationResourceUnavailable
        return ReservationLifecycleResult(
            UUID(str(row[0])),
            UUID(str(row[1])),
            ReservationStatus(str(row[2])),
            str(row[3]),
            CancellationResponsibility(str(row[4])),
            cast(date, row[5]),
            int(str(row[6])),
            str(row[7]),
            int(str(row[8])),
            UUID(str(row[9])),
            int(str(row[10])),
            DepositOutcomeState(str(row[11])),
            UUID(str(row[12])),
            None if row[13] is None else str(row[13]),
        )

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        self._service(property_id, actor).create(command)
        return self.get(command.reservation_id)

    def extend(
        self,
        command: ReservationExtendCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        current = self.get(command.reservation_id)
        self._service(current.property_id, actor).extend(command)
        return self.get(command.reservation_id)

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        current = self.get(command.reservation_id)
        self._service(current.property_id, actor).cancel(command, actor=actor)
        return self.get(command.reservation_id)


class ReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: UUID
    unit_id: UUID
    customer_id: UUID
    reservation_date: date
    agreed_monthly_rent_usd_cents: Annotated[int, Field(gt=0)]
    expiration_date: date
    acceptance_id: UUID
    accepted_initial_deposit_usd_cents: Annotated[int, Field(gt=0)]
    required_security_deposit_usd_cents: Annotated[int, Field(gt=0)]
    acceptance_reason: Annotated[str, Field(min_length=1, max_length=500)]
    deposit_id: UUID
    receipt_id: UUID
    payment_id: UUID
    received_at: datetime


class ReservationExtend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_id: UUID
    new_expiration_date: date
    approved_at: datetime
    reason_memo: Annotated[str, Field(max_length=500)] = ""


class ReservationCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    outcome_id: UUID
    reason_code: Annotated[str, Field(min_length=1, max_length=100)]
    responsibility: CancellationResponsibility
    property_could_provide_unit: bool
    reason_memo: Annotated[str, Field(max_length=500)] = ""
    coordination_reference: Annotated[str | None, Field(max_length=255)] = None
    refund_number: Annotated[str | None, Field(max_length=100)] = None


def _require_actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _can(actor: AuthenticatedActor, property_id: UUID, capability: str) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(capability=capability, property_id=str(property_id)),
    )


def _require(actor: AuthenticatedActor, property_id: UUID, capability: str) -> None:
    if not _can(actor, property_id, capability):
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


def _body(resource: ReservationResource, actor: AuthenticatedActor) -> dict[str, object]:
    result = asdict(resource)
    result.update(
        {
            "reservation_id": str(resource.reservation_id),
            "property_id": str(resource.property_id),
            "unit_id": str(resource.unit_id),
            "customer_id": str(resource.customer_id),
            "deposit_id": str(resource.deposit_id),
            "resulting_lease_id": (
                None if resource.resulting_lease_id is None else str(resource.resulting_lease_id)
            ),
            "can_extend": resource.status is ReservationStatus.ACTIVE
            and resource.extension_notice is None
            and resource.extension_eligible
            and _can(actor, resource.property_id, RESERVATION_EXTEND_CAPABILITY),
            "can_cancel": resource.status is ReservationStatus.ACTIVE
            and _can(actor, resource.property_id, RESERVATION_CANCEL_CAPABILITY),
        }
    )
    if resource.extension_notice is not None:
        result["extension_notice"] = {
            **asdict(resource.extension_notice),
            "notice_id": str(resource.extension_notice.notice_id),
        }
    return result


def _lifecycle_body(result: ReservationLifecycleResult) -> dict[str, object]:
    """Render only the transaction-persisted result so API-016 replay stays exact."""
    return {
        "reservation_id": str(result.reservation_id),
        "unit_id": str(result.unit_id),
        "status": result.status.value,
        "cancellation_reason_code": result.cancellation_reason_code,
        "cancellation_responsibility": result.cancellation_responsibility.value,
        "effective_expiration_date": result.effective_expiration_date.isoformat(),
        "version": result.version,
        "unit_status": result.unit_status,
        "unit_version": result.unit_version,
        "deposit_id": str(result.deposit_id),
        "deposit_received_usd_cents": result.deposit_received_usd_cents,
        "deposit_outcome_state": result.deposit_outcome_state.value,
        "outcome_id": str(result.outcome_id),
        "refund_number": result.refund_number,
    }


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, DepositIdempotencyKeyReused):
        return exc  # type: ignore[return-value]
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, (ReservationResourceNotFound, ReservationNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, ReservationVersionConflictError):
        return HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    if isinstance(exc, ReservationCommandConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, (ReservationCommandInvalidError, ReservationResourceInvalid, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, ReservationAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def create_reservation_router(
    resolver: ActorResolver,
    flow: ReservationResourceFlow,
    settings: Settings,
) -> APIRouter:
    """Create API-032 through API-034 routes without a generic status patch."""
    router = APIRouter(tags=["reservations"])

    @router.get("/properties/{property_id}/reservations")
    def list_reservations(
        property_id: UUID,
        request: Request,
        response: Response,
        reservation_status: Annotated[ReservationStatus | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require(actor, property_id, RESERVATION_READ_CAPABILITY)
        try:
            page = flow.list(
                property_id,
                reservation_status=reservation_status,
                limit=limit,
                cursor=cursor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": {
                "items": [_body(item, actor) for item in page.items],
                "next_cursor": page.next_cursor,
                "can_create": _can(actor, property_id, RESERVATION_CREATE_CAPABILITY),
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/properties/{property_id}/reservations", status_code=status.HTTP_201_CREATED)
    def create_reservation(
        property_id: UUID,
        source: ReservationCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require(actor, property_id, RESERVATION_CREATE_CAPABILITY)
        require_browser_mutation(request, settings)
        suggested = (source.agreed_monthly_rent_usd_cents + 2) // 5
        acceptance_kind = (
            "NORMAL_SUGGESTION"
            if source.accepted_initial_deposit_usd_cents == suggested
            else "AUTHORIZED_VARIANCE"
        )
        if acceptance_kind == "AUTHORIZED_VARIANCE":
            _require(actor, property_id, DEPOSIT_OVERRIDE_CAPABILITY)
        command = ReservationCreateCommand(
            idempotency_key=idempotency_key,
            reservation_id=source.reservation_id,
            unit_id=source.unit_id,
            customer_id=source.customer_id,
            reservation_date=source.reservation_date,
            agreed_monthly_rent_usd_cents=source.agreed_monthly_rent_usd_cents,
            original_expiration_date=source.expiration_date,
            acceptance_id=source.acceptance_id,
            accepted_required_amount_usd_cents=source.accepted_initial_deposit_usd_cents,
            acceptance_kind=acceptance_kind,
            accepted_at=source.received_at,
            acceptance_reason=source.acceptance_reason,
            authorization_reference=(
                RESERVATION_CREATE_CAPABILITY
                if acceptance_kind == "NORMAL_SUGGESTION"
                else DEPOSIT_OVERRIDE_CAPABILITY
            ),
            calculation_trace={
                "agreed_monthly_rent_usd_cents": source.agreed_monthly_rent_usd_cents,
                "suggested_rate_basis_points": 2000,
                "suggested_amount_usd_cents": suggested,
            },
            deposit_id=source.deposit_id,
            required_deposit_usd_cents=source.required_security_deposit_usd_cents,
            receipt_id=source.receipt_id,
            payment_id=source.payment_id,
            received_at=source.received_at,
        )
        try:
            resource = flow.create(property_id, command, actor=actor)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/reservations/{resource.reservation_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.get("/reservations/{reservation_id}")
    def get_reservation(
        reservation_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(reservation_id)
        except Exception as exc:
            raise _translate(exc) from exc
        _require(actor, resource.property_id, RESERVATION_READ_CAPABILITY)
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/extend")
    def extend_reservation(
        reservation_id: UUID,
        source: ReservationExtend,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_EXTEND_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.extend(
                ReservationExtendCommand(
                    idempotency_key=idempotency_key,
                    notice_id=source.notice_id,
                    reservation_id=reservation_id,
                    expected_version=_version(if_match),
                    new_expiration_date=source.new_expiration_date,
                    approved_at=source.approved_at,
                    reason_memo=source.reason_memo,
                    authorization_reference=RESERVATION_EXTEND_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/cancel")
    def cancel_reservation(
        reservation_id: UUID,
        source: ReservationCancel,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_CANCEL_CAPABILITY)
            require_browser_mutation(request, settings)
            outcome_capability = (
                "reservation_deposits.dispose"
                if source.responsibility is CancellationResponsibility.CUSTOMER
                else "reservation_deposits.refund"
            )
            resource = flow.cancel(
                ReservationCancelCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    outcome_id=source.outcome_id,
                    reservation_id=reservation_id,
                    expected_version=_version(if_match),
                    reason_code=source.reason_code,
                    responsibility=source.responsibility,
                    property_could_provide_unit=source.property_could_provide_unit,
                    reason_memo=source.reason_memo,
                    coordination_reference=source.coordination_reference,
                    authorization_reference=RESERVATION_CANCEL_CAPABILITY,
                    outcome_authorization_reference=outcome_capability,
                    refund_number=source.refund_number,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/api/v1/reservations/{reservation_id}/security-deposit-dispositions")
    def create_reservation_security_deposit_disposition(
        reservation_id: UUID,
        source: ReservationCancel,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """Atomically classify customer cancellation and its Security Deposit outcome."""
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_security_deposit_disposition(reservation_id)
            _require(actor, property_id, RESERVATION_CANCEL_CAPABILITY)
            _require(actor, property_id, "reservation_deposits.dispose")
            require_browser_mutation(request, settings)
            if source.responsibility is not CancellationResponsibility.CUSTOMER:
                raise ReservationResourceInvalid(
                    "The disposition endpoint accepts only customer-caused outcomes"
                )
            if if_match is None:
                raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
            result = flow.create_security_deposit_disposition(
                ReservationCancelCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    outcome_id=source.outcome_id,
                    reservation_id=reservation_id,
                    expected_version=_version(if_match),
                    reason_code=source.reason_code,
                    responsibility=source.responsibility,
                    property_could_provide_unit=source.property_could_provide_unit,
                    reason_memo=source.reason_memo,
                    coordination_reference=source.coordination_reference,
                    authorization_reference=RESERVATION_CANCEL_CAPABILITY,
                    outcome_authorization_reference="reservation_deposits.dispose",
                    refund_number=source.refund_number,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{result.version}"'
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _lifecycle_body(result),
            "meta": {"request_id": request.state.request_id},
        }

    return router
