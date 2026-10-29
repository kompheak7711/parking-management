"""Authorized Deposit resources and corrected bounded V1-038 workflows."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Annotated, Final, Protocol, cast
from uuid import UUID, uuid5

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.api_refusals import (
    DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED,
    DEPOSIT_RECEIPT_FORFEITURE_ACTIVE,
    DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT,
    DEPOSIT_RECEIPT_LEASE_NOT_SIGNED,
    DEPOSIT_RECEIPT_OVER_PAYMENT,
    DEPOSIT_RECEIPT_OVER_REQUIRED,
    DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED,
    DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE,
    DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND,
    DEPOSIT_RECEIPT_PAYMENT_OWED,
    DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE,
    DEPOSIT_SECURITY_ALREADY_EXISTS,
    DEPOSIT_SECURITY_LEASE_NOT_SIGNED,
    DEPOSIT_SECURITY_NOT_WALK_IN,
    DEPOSIT_SECURITY_RENEWAL,
    FINAL_SETTLEMENT_CLOSED,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.browser_security import require_browser_mutation
from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_CORRECT_CAPABILITY,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_MANAGE_CAPABILITY,
    DEPOSIT_QUERY_TIMEOUT_MS,
    DEPOSIT_REFUND_QUALIFY_CAPABILITY,
    ONE_STEP_NAMESPACE,
    PAYMENT_ALLOCATE_CAPABILITY,
    CreateLeaseSecurityDepositCommand,
    CreatePetDepositCommand,
    DepositAuthorizationError,
    DepositConflictError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    DepositNotFoundError,
    DepositReceiptRecord,
    DepositReceiptReversalDraftRequired,
    DepositServiceUnavailableError,
    DepositSnapshot,
    LeaseDepositDraftRequired,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositReceiptCommand,
    RecordPetDepartureCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.financial_context import bind_financial_property
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import OwnMoneyInput
from property_rental.reservation import (
    DEPOSIT_DISPOSITION_CAPABILITY as RESERVATION_DEPOSIT_DISPOSITION_CAPABILITY,
)
from property_rental.reservation import (
    DEPOSIT_OUTCOME_CORRECT_CAPABILITY,
    ReservationAuthorizationError,
    ReservationCommandConflictError,
    ReservationCommandInvalidError,
    ReservationDepositDraftRequired,
    ReservationNotFoundError,
    ReservationServiceUnavailableError,
    ReservationVersionConflictError,
)
from property_rental.settings import Settings

DEPOSIT_READ_CAPABILITY: Final = "deposits.read"
PAYMENT_RECORD_CAPABILITY: Final = "payments.record"
MAX_LEDGER_PAGE_SIZE: Final = 100

_CLOSED_SETTLEMENT = "A closed Final Settlement changes only through a post-settlement correction"
# V1-056 slice 11c-4: the business-state refusals of the walk-in Security Deposit create and of a
# receipt into an existing Deposit, by their database message (read from the head catalog).
SECURITY_DEPOSIT_REFUSALS: Final[dict[str, Refusal]] = {
    "Signed Lease was not found": DEPOSIT_SECURITY_LEASE_NOT_SIGNED,
    "Only a walk-in Lease's Security Deposit is created here": DEPOSIT_SECURITY_NOT_WALK_IN,
    "A renewal Lease's Security Deposit is not created here": DEPOSIT_SECURITY_RENEWAL,
    "The Lease already has a Security Deposit": DEPOSIT_SECURITY_ALREADY_EXISTS,
    _CLOSED_SETTLEMENT: FINAL_SETTLEMENT_CLOSED,
}
DEPOSIT_RECEIPT_REFUSALS: Final[dict[str, Refusal]] = {
    "Payment was not found": DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND,
    "The Deposit's Lease is not signed": DEPOSIT_RECEIPT_LEASE_NOT_SIGNED,
    "The Deposit's Reservation is not active; this receipt is not recorded here": (
        DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE
    ),
    "The Lease's termination ground keeps this Deposit; this receipt is not recorded here": (
        DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT
    ),
    "The Deposit has an active forfeiture; reverse the forfeiture first": (
        DEPOSIT_RECEIPT_FORFEITURE_ACTIVE
    ),
    "Applicable obligations must be handled before excess disposition": (
        DEPOSIT_RECEIPT_PAYMENT_OWED
    ),
    "Deposit receipt Payment source is ineligible": DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE,
    "Deposit receipt exceeds Payment availability": DEPOSIT_RECEIPT_OVER_PAYMENT,
    "A Deposit holds at most one active receipt from each Payment": (
        DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED
    ),
    # A Reservation's Security Deposit with no active receipt takes exactly its accepted amount,
    # so this message also covers an amount below it (review round 1).
    "Deposit receipt does not preserve the accepted or required amount": (
        DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED
    ),
    "Pet Deposit receipt exceeds its approved liability": DEPOSIT_RECEIPT_OVER_REQUIRED,
    _CLOSED_SETTLEMENT: FINAL_SETTLEMENT_CLOSED,
}


class DepositResourceNotFound(LookupError):
    pass


class DepositResourceUnavailable(RuntimeError):
    pass


class DepositResourceInvalid(ValueError):
    pass


def deposit_idempotency_key_reused_response(request: Request) -> JSONResponse:
    """Return the dedicated API-016 conflict without stored-command details."""
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


@dataclass(frozen=True, slots=True)
class DepositLedgerEvent:
    event_id: UUID
    event_kind: str
    occurred_at: datetime
    amount_usd_cents: int | None
    source_id: UUID | None
    reason: str | None
    evidence_reference: str | None
    actor_id: UUID
    authorization_reference: str | None
    currency: str | None
    amount_minor: int | None
    reference_number: str | None
    governing_source_kind: str | None
    governing_source_id: UUID | None
    source_lifecycle_event_id: UUID | None
    effective_date: date | None
    reversal_eligible: bool


@dataclass(frozen=True, slots=True)
class DepositLedgerPage:
    items: tuple[DepositLedgerEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class PetDepartureResource:
    departure_id: UUID
    deposit_id: UUID
    lease_id: UUID
    pet_approval_id: UUID
    permanently_left_date: date
    reason: str
    occurred_at: datetime
    actor_id: UUID
    refund_review_id: UUID | None


@dataclass(frozen=True, slots=True)
class PetRefundReviewResource:
    review_id: UUID
    departure_id: UUID
    deposit_id: UUID
    obligations_reviewed_usd_cents: int
    review_findings: str
    resolution_reference: str
    reason: str
    reviewed_at: datetime
    reviewed_by: UUID
    authorization_reference: str
    refundable_usd_cents: int
    current_refundable_usd_cents: int


class DepositResourceFlow(Protocol):
    def property_for_reservation(self, reservation_id: UUID) -> UUID: ...

    def property_for_lease(self, lease_id: UUID) -> UUID: ...

    def property_for_receipt(self, receipt_id: UUID) -> UUID: ...

    def disposition_context(self, disposition_id: UUID) -> tuple[UUID, UUID | None]: ...

    def property_for_departure(self, departure_id: UUID) -> UUID: ...

    def property_for_review(self, review_id: UUID) -> UUID: ...

    def list_for_reservation(self, reservation_id: UUID) -> tuple[DepositSnapshot, ...]: ...

    def list_for_lease(self, lease_id: UUID) -> tuple[DepositSnapshot, ...]: ...

    def get(self, deposit_id: UUID) -> DepositSnapshot: ...

    def ledger(self, deposit_id: UUID, *, limit: int, cursor: str | None) -> DepositLedgerPage: ...

    def create_pet_deposit(
        self, property_id: UUID, command: CreatePetDepositCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot: ...

    def create_lease_security_deposit(
        self,
        property_id: UUID,
        command: CreateLeaseSecurityDepositCommand,
        *,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot: ...

    def record_receipt(
        self, property_id: UUID, command: RecordDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositReceiptRecord: ...

    def lease_payer(self, lease_id: UUID) -> tuple[UUID, UUID]:
        """The Lease's Property and its Primary Tenant (V1-061, DL-112)."""
        ...

    def receive_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        payment: dict[str, object],
        create: CreateLeaseSecurityDepositCommand | None,
        receipt: RecordDepositReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> tuple[DepositReceiptRecord, dict[str, object]]: ...

    def reverse_receipt(
        self, receipt_id: UUID, command: ReverseDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot: ...

    def reverse_disposition(
        self,
        disposition_id: UUID,
        command: ReverseDepositDispositionCommand,
        *,
        replacement_disposition_id: UUID | None,
        expected_reservation_version: int | None,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot: ...

    def record_departure(
        self, lease_id: UUID, command: RecordPetDepartureCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot: ...

    def qualify_review(
        self,
        departure_id: UUID,
        command: QualifyPetDepositRefundReviewCommand,
        *,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot: ...

    def departures(self, lease_id: UUID) -> tuple[PetDepartureResource, ...]: ...

    def review(self, review_id: UUID) -> PetRefundReviewResource: ...


@dataclass(frozen=True, slots=True)
class UnavailableDepositResourceFlow:
    def _unavailable(self) -> None:
        raise DepositResourceUnavailable

    def __getattr__(self, _: str) -> object:
        return self._unavailable


def _cursor(value: tuple[datetime, UUID]) -> str:
    raw = json.dumps([value[0].isoformat(), str(value[1])], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, identity = json.loads(raw)
        return datetime.fromisoformat(str(timestamp)), UUID(str(identity))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DepositResourceInvalid("Deposit ledger cursor is invalid") from exc


@dataclass(frozen=True, slots=True)
class PostgresDepositResourceFlow:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _bound_query(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
            (str(DEPOSIT_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
            (str(DEPOSIT_QUERY_TIMEOUT_MS),),
        )

    def _fetchone(self, query: str, parameters: tuple[object, ...]) -> tuple[object, ...]:
        try:
            with psycopg.connect(
                self.database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise DepositResourceUnavailable from exc
        if row is None:
            raise DepositResourceNotFound
        return row

    def _fetchall(self, query: str, parameters: tuple[object, ...]) -> list[tuple[object, ...]]:
        try:
            with psycopg.connect(
                self.database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                return list(connection.execute(query, parameters).fetchall())
        except psycopg.Error as exc:
            raise DepositResourceUnavailable from exc

    def _financial_snapshot(self, query: str, parameters: tuple[object, ...]) -> DepositSnapshot:
        if self.financial_database_url is None:
            raise ReservationAuthorizationError(
                "Dedicated Reservation financial persistence is unavailable"
            )
        try:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                self._bound_query(connection)
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise ReservationNotFoundError("Reservation resource was not found") from exc
            if exc.sqlstate == "40001":
                raise ReservationVersionConflictError(
                    "Reservation version precondition was not met"
                ) from exc
            if (exc.sqlstate == "P0001" and "idempotency key was reused" in str(exc).lower()) or (
                exc.sqlstate == "23505"
                and "deposit idempotency key conflicts with another request" in str(exc).lower()
            ):
                raise DepositIdempotencyKeyReused("Reservation idempotency key was reused") from exc
            if exc.sqlstate in {"P0001", "23505"}:
                raise ReservationCommandConflictError("Reservation command conflicted") from exc
            if exc.sqlstate in {"22023", "23514", "55000"}:
                raise ReservationCommandInvalidError("Reservation command is invalid") from exc
            raise ReservationServiceUnavailableError(
                "Reservation persistence is unavailable"
            ) from exc
        if row is None:
            raise ReservationServiceUnavailableError("Reservation command returned no result")
        return self._snapshot(row)

    @staticmethod
    def _snapshot(row: tuple[object, ...]) -> DepositSnapshot:
        if row[0] is None:
            raise DepositResourceNotFound
        value = cast(dict[str, object], row[0])

        def optional_uuid(key: str) -> UUID | None:
            raw = value.get(key)
            return None if raw is None else UUID(str(raw))

        from property_rental.deposit import DepositType

        return DepositSnapshot(
            UUID(str(value["deposit_id"])),
            UUID(str(value["property_id"])),
            DepositType(str(value["deposit_type"])),
            UUID(str(value["customer_id"])),
            optional_uuid("reservation_id"),
            optional_uuid("lease_id"),
            optional_uuid("pet_approval_id"),
            int(str(value["required_usd_cents"])),
            int(str(value["received_usd_cents"])),
            int(str(value["held_refundable_usd_cents"])),
            int(str(value["outstanding_required_usd_cents"])),
            int(str(value["version"])),
            optional_uuid("pet_departure_id"),
            optional_uuid("pet_refund_review_id"),
            optional_uuid("deposit_disposition_id"),
            optional_uuid("deposit_disposition_reversal_id"),
            bool(value.get("refund_qualified", False)),
            (
                None
                if value.get("reservation_version") is None
                else int(str(value["reservation_version"]))
            ),
        )

    def property_for_reservation(self, reservation_id: UUID) -> UUID:
        return UUID(
            str(
                self._fetchone(
                    "SELECT unit.property_id FROM app.reservations AS reservation "
                    "JOIN app.units AS unit ON unit.id=reservation.unit_id "
                    "WHERE reservation.id=%s",
                    (reservation_id,),
                )[0]
            )
        )

    def property_for_lease(self, lease_id: UUID) -> UUID:
        return UUID(
            str(
                self._fetchone(
                    "SELECT unit.property_id FROM app.leases AS lease "
                    "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE lease.id=%s",
                    (lease_id,),
                )[0]
            )
        )

    def property_for_receipt(self, receipt_id: UUID) -> UUID:
        return UUID(
            str(
                self._fetchone(
                    "SELECT unit.property_id FROM app.deposit_receipts AS receipt "
                    "JOIN app.deposits AS deposit ON deposit.id=receipt.deposit_id "
                    "LEFT JOIN app.reservations AS reservation "
                    "ON reservation.id=deposit.reservation_id "
                    "LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id "
                    "JOIN app.units AS unit ON unit.id=COALESCE(reservation.unit_id,lease.unit_id) "
                    "WHERE receipt.id=%s",
                    (receipt_id,),
                )[0]
            )
        )

    def disposition_context(self, disposition_id: UUID) -> tuple[UUID, UUID | None]:
        row = self._fetchone(
            "SELECT unit.property_id,disposition.governing_reservation_id "
            "FROM app.deposit_dispositions AS disposition "
            "JOIN app.deposits AS deposit ON deposit.id=disposition.deposit_id "
            "LEFT JOIN app.reservations AS reservation ON reservation.id=deposit.reservation_id "
            "LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id "
            "JOIN app.units AS unit ON unit.id=COALESCE(reservation.unit_id,lease.unit_id) "
            "WHERE disposition.id=%s",
            (disposition_id,),
        )
        return UUID(str(row[0])), None if row[1] is None else UUID(str(row[1]))

    def property_for_departure(self, departure_id: UUID) -> UUID:
        return UUID(
            str(
                self._fetchone(
                    "SELECT unit.property_id FROM app.lease_pet_departures AS departure "
                    "JOIN app.leases AS lease ON lease.id=departure.lease_id "
                    "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE departure.id=%s",
                    (departure_id,),
                )[0]
            )
        )

    def property_for_review(self, review_id: UUID) -> UUID:
        return UUID(
            str(
                self._fetchone(
                    "SELECT unit.property_id "
                    "FROM app.pet_deposit_refund_reviews AS review "
                    "JOIN app.deposits AS deposit ON deposit.id=review.pet_deposit_id "
                    "JOIN app.leases AS lease ON lease.id=deposit.lease_id "
                    "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE review.id=%s",
                    (review_id,),
                )[0]
            )
        )

    def list_for_reservation(self, reservation_id: UUID) -> tuple[DepositSnapshot, ...]:
        return tuple(
            self._snapshot(row)
            for row in self._fetchall(
                "SELECT app.deposit_resource_snapshot(id) FROM app.deposits "
                "WHERE reservation_id=%s ORDER BY required_effective_date,id LIMIT 10",
                (reservation_id,),
            )
        )

    def list_for_lease(self, lease_id: UUID) -> tuple[DepositSnapshot, ...]:
        return tuple(
            self._snapshot(row)
            for row in self._fetchall(
                "SELECT app.deposit_resource_snapshot(id) FROM app.deposits "
                "WHERE lease_id=%s ORDER BY deposit_type,required_effective_date,id LIMIT 10",
                (lease_id,),
            )
        )

    def get(self, deposit_id: UUID) -> DepositSnapshot:
        return self._snapshot(
            self._fetchone("SELECT app.deposit_resource_snapshot(%s)", (deposit_id,))
        )

    def ledger(self, deposit_id: UUID, *, limit: int, cursor: str | None) -> DepositLedgerPage:
        snapshot = self.get(deposit_id)
        decoded = _decode_cursor(cursor)
        rows = self._fetchall(
            """
            WITH history AS (
                SELECT receipt.id event_id,'RECEIPT' event_kind,receipt.occurred_at,
                    receipt.amount_usd_cents,receipt.payment_id source_id,NULL::text reason,
                    NULL::text evidence_reference,receipt.actor_id,
                    NULL::text authorization_reference,'USD'::text currency,
                    receipt.amount_usd_cents amount_minor,NULL::text reference_number,
                    NULL::text governing_source_kind,NULL::uuid governing_source_id,
                    NULL::uuid source_lifecycle_event_id,NULL::date effective_date,
                    NOT EXISTS (
                        SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                        WHERE reversal.deposit_receipt_id=receipt.id
                    ) AND NOT EXISTS (
                        SELECT 1 FROM app.deposit_dispositions AS disposition
                        WHERE disposition.deposit_id=receipt.deposit_id
                          AND NOT EXISTS (
                              SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                              WHERE reversal.deposit_disposition_id=disposition.id
                          )
                    ) AND NOT EXISTS (
                        SELECT 1 FROM app.refunds AS refund
                        WHERE refund.source_deposit_id=receipt.deposit_id
                          AND refund.usd_accounting_value_cents<>COALESCE((
                              SELECT sum(correction.source_balance_effect_usd_cents)
                              FROM app.refund_corrections AS correction
                              WHERE correction.refund_id=refund.id
                          ),0)
                    ) AND NOT app.deposit_has_active_application(receipt.deposit_id)
                    reversal_eligible
                FROM app.deposit_receipts AS receipt WHERE receipt.deposit_id=%s
                UNION ALL
                SELECT reversal.id,'RECEIPT_REVERSAL',reversal.occurred_at,
                    receipt.amount_usd_cents,receipt.id,reversal.reason,NULL::text,
                    reversal.actor_id,reversal.authorization_reference,
                    'USD'::text,receipt.amount_usd_cents,NULL::text,
                    NULL::text,NULL::uuid,NULL::uuid,NULL::date,false
                FROM app.deposit_receipt_reversals AS reversal
                JOIN app.deposit_receipts AS receipt ON receipt.id=reversal.deposit_receipt_id
                WHERE receipt.deposit_id=%s
                UNION ALL
                SELECT disposition.id,'DISPOSITION',disposition.occurred_at,
                    disposition.amount_usd_cents,
                    COALESCE(disposition.governing_reservation_id,disposition.governing_lease_id),
                    disposition.reason,NULL::text,disposition.actor_id,
                    disposition.authorization_reference,'USD'::text,
                    disposition.amount_usd_cents,NULL::text,
                    CASE WHEN disposition.governing_reservation_id IS NOT NULL
                        THEN 'RESERVATION' ELSE 'LEASE' END,
                    COALESCE(disposition.governing_reservation_id,
                        disposition.governing_lease_id),
                    disposition.source_lifecycle_event_id,disposition.effective_date,
                    NOT EXISTS (
                        SELECT 1 FROM app.deposit_disposition_reversals AS reversal
                        WHERE reversal.deposit_disposition_id=disposition.id
                    )
                FROM app.deposit_dispositions AS disposition WHERE disposition.deposit_id=%s
                UNION ALL
                SELECT reversal.id,'DISPOSITION_REVERSAL',reversal.occurred_at,
                    disposition.amount_usd_cents,disposition.id,reversal.reason,
                    reversal.evidence_reference,reversal.actor_id,reversal.authorization_reference,
                    'USD'::text,disposition.amount_usd_cents,NULL::text,
                    CASE WHEN disposition.governing_reservation_id IS NOT NULL
                        THEN 'RESERVATION' ELSE 'LEASE' END,
                    COALESCE(disposition.governing_reservation_id,
                        disposition.governing_lease_id),
                    disposition.source_lifecycle_event_id,disposition.effective_date,false
                FROM app.deposit_disposition_reversals AS reversal
                JOIN app.deposit_dispositions AS disposition
                  ON disposition.id=reversal.deposit_disposition_id
                WHERE disposition.deposit_id=%s
                UNION ALL
                SELECT adjustment.id,'REQUIRED_AMOUNT_' || adjustment.adjustment_type,
                    adjustment.occurred_at,adjustment.amount_usd_cents,NULL::uuid,
                    adjustment.reason,NULL::text,adjustment.actor_id,
                    adjustment.authorization_reference,'USD'::text,
                    adjustment.amount_usd_cents,NULL::text,
                    NULL::text,NULL::uuid,NULL::uuid,adjustment.effective_date,false
                FROM app.deposit_required_amount_adjustments AS adjustment
                WHERE adjustment.deposit_id=%s
                UNION ALL
                SELECT departure.id,'PET_DEPARTURE',departure.occurred_at,NULL::bigint,
                    departure.pet_approval_id,departure.reason,NULL::text,departure.actor_id,
                    command.authorization_reference,NULL::text,NULL::bigint,NULL::text,
                    'LEASE'::text,departure.lease_id,NULL::uuid,
                    departure.permanently_left_date,false
                FROM app.lease_pet_departures AS departure
                JOIN app.deposits AS deposit ON deposit.pet_approval_id=departure.pet_approval_id
                LEFT JOIN LATERAL (
                    SELECT source.authorization_reference
                    FROM app.deposit_commands AS source
                    WHERE source.action IN (
                        'deposit.pet_departure.record','deposit.pet_refund.qualify'
                    )
                      AND source.deposit_id=deposit.id
                      AND source.result_snapshot ->> 'pet_departure_id'=departure.id::text
                    ORDER BY source.created_at DESC LIMIT 1
                ) AS command ON true
                WHERE deposit.id=%s
                UNION ALL
                SELECT review.id,'PET_REFUND_REVIEW',review.reviewed_at,
                    review.obligations_reviewed_usd_cents,review.pet_departure_id,
                    review.reason,review.resolution_reference,review.reviewed_by,
                    review.authorization_reference,'USD'::text,
                    review.obligations_reviewed_usd_cents,NULL::text,
                    'LEASE'::text,deposit.lease_id,NULL::uuid,NULL::date,false
                FROM app.pet_deposit_refund_reviews AS review
                JOIN app.deposits AS deposit ON deposit.id=review.pet_deposit_id
                WHERE review.pet_deposit_id=%s
                UNION ALL
                SELECT refund.id,'REFUND',refund.processed_at,
                    refund.usd_accounting_value_cents,refund.source_lifecycle_event_id,
                    refund.reason,NULL::text,refund.processed_by,refund.authorization_reference,
                    refund.refund_currency,refund.refund_amount_minor,refund.refund_number
                    ,CASE WHEN refund.source_lifecycle_event_id IS NULL
                        THEN NULL::text ELSE 'RESERVATION'::text END,
                    deposit.reservation_id,refund.source_lifecycle_event_id,NULL::date,false
                FROM app.refunds AS refund
                JOIN app.deposits AS deposit ON deposit.id=refund.source_deposit_id
                WHERE refund.source_deposit_id=%s
                UNION ALL
                SELECT correction.id,'REFUND_' || correction.correction_kind,
                    correction.occurred_at,correction.source_balance_effect_usd_cents,
                    correction.refund_id,correction.reason,correction.evidence_reference,
                    correction.actor_id,correction.authorization_reference,
                    refund.refund_currency,correction.source_balance_effect_usd_cents,
                    refund.refund_number,
                    CASE WHEN refund.source_lifecycle_event_id IS NULL
                        THEN NULL::text ELSE 'RESERVATION'::text END,
                    deposit.reservation_id,refund.source_lifecycle_event_id,NULL::date,false
                FROM app.refund_corrections AS correction
                JOIN app.refunds AS refund ON refund.id=correction.refund_id
                JOIN app.deposits AS deposit ON deposit.id=refund.source_deposit_id
                WHERE refund.source_deposit_id=%s
                UNION ALL
                -- A Final Settlement Deposit application (BR-SETTLE-009): every lower held
                -- amount has its event; the source is the Invoice line or Late-payment Charge.
                -- The runtime role reads applications only through this bounded function.
                SELECT application.application_id,'APPLICATION_' || application.target_kind,
                    application.occurred_at,application.amount_usd_cents,application.target_id,
                    application.reason,NULL::text,application.actor_id,
                    application.authorization_reference,'USD'::text,
                    application.amount_usd_cents,NULL::text,
                    'FINAL_SETTLEMENT'::text,application.final_settlement_id,NULL::uuid,
                    NULL::date,false
                FROM app.deposit_application_history(%s,%s) AS application
                UNION ALL
                -- The reversal of such an application by a post-settlement correction
                -- (DB-DEP-006): the Deposit holds the amount again.
                SELECT reversal.reversal_id,'APPLICATION_REVERSAL_' || reversal.target_kind,
                    reversal.occurred_at,reversal.amount_usd_cents,reversal.application_id,
                    reversal.reason,NULL::text,reversal.actor_id,
                    reversal.authorization_reference,'USD'::text,
                    reversal.amount_usd_cents,NULL::text,
                    'FINAL_SETTLEMENT'::text,reversal.final_settlement_id,NULL::uuid,
                    NULL::date,false
                FROM app.deposit_application_reversal_history(%s,%s) AS reversal
            )
            SELECT event_id,event_kind,occurred_at,amount_usd_cents,source_id,reason,
                   evidence_reference,actor_id,authorization_reference,currency,
                   amount_minor,reference_number,governing_source_kind,
                   governing_source_id,source_lifecycle_event_id,effective_date,
                   reversal_eligible
            FROM history
            WHERE (%s::timestamptz IS NULL OR (occurred_at,event_id) < (%s,%s))
            ORDER BY occurred_at DESC,event_id DESC LIMIT %s
            """,
            (
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                deposit_id,
                snapshot.property_id,
                deposit_id,
                snapshot.property_id,
                deposit_id,
                None if decoded is None else decoded[0],
                None if decoded is None else decoded[0],
                None if decoded is None else decoded[1],
                limit + 1,
            ),
        )
        values = tuple(
            DepositLedgerEvent(
                UUID(str(row[0])),
                str(row[1]),
                cast(datetime, row[2]),
                None if row[3] is None else int(str(row[3])),
                None if row[4] is None else UUID(str(row[4])),
                None if row[5] is None else str(row[5]),
                None if row[6] is None else str(row[6]),
                UUID(str(row[7])),
                None if row[8] is None else str(row[8]),
                None if row[9] is None else str(row[9]),
                None if row[10] is None else int(str(row[10])),
                None if row[11] is None else str(row[11]),
                None if row[12] is None else str(row[12]),
                None if row[13] is None else UUID(str(row[13])),
                None if row[14] is None else UUID(str(row[14])),
                None if row[15] is None else cast(date, row[15]),
                bool(row[16]),
            )
            for row in rows[:limit]
        )
        next_cursor = None
        if len(rows) > limit and values:
            next_cursor = _cursor((values[-1].occurred_at, values[-1].event_id))
        return DepositLedgerPage(values, next_cursor)

    def _service(self, property_id: UUID, actor: AuthenticatedActor) -> PostgresDepositService:
        if self.financial_database_url is None:
            raise DepositResourceUnavailable
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise DepositAuthorizationError("Deposit actor is invalid") from exc
        return PostgresDepositService(self.financial_database_url, property_id, actor_id)

    def create_pet_deposit(
        self, property_id: UUID, command: CreatePetDepositCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        return self._service(property_id, actor).create_pet_deposit(command, actor=actor)

    def create_lease_security_deposit(
        self,
        property_id: UUID,
        command: CreateLeaseSecurityDepositCommand,
        *,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot:
        return self._service(property_id, actor).create_lease_security_deposit(command, actor=actor)

    def record_receipt(
        self, property_id: UUID, command: RecordDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositReceiptRecord:
        return self._service(property_id, actor).record_receipt(command, actor=actor)

    def lease_payer(self, lease_id: UUID) -> tuple[UUID, UUID]:
        row = self._fetchone(
            "SELECT unit.property_id, lease.primary_tenant_id FROM app.leases AS lease "
            "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE lease.id=%s",
            (lease_id,),
        )
        return UUID(str(row[0])), UUID(str(row[1]))

    def receive_with_payment(
        self,
        property_id: UUID,
        lease_id: UUID,
        payment: dict[str, object],
        create: CreateLeaseSecurityDepositCommand | None,
        receipt: RecordDepositReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> tuple[DepositReceiptRecord, dict[str, object]]:
        return self._service(property_id, actor).receive_with_payment(
            lease_id, payment, create, receipt, actor=actor
        )

    def reverse_receipt(
        self, receipt_id: UUID, command: ReverseDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        deposit_id = UUID(
            str(
                self._fetchone(
                    "SELECT deposit_id FROM app.deposit_receipts WHERE id=%s", (receipt_id,)
                )[0]
            )
        )
        current = self.get(deposit_id)
        return self._service(current.property_id, actor).reverse_receipt(command, actor=actor)

    def reverse_disposition(
        self,
        disposition_id: UUID,
        command: ReverseDepositDispositionCommand,
        *,
        replacement_disposition_id: UUID | None,
        expected_reservation_version: int | None,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot:
        row = self._fetchone(
            "SELECT deposit_id,governing_reservation_id FROM app.deposit_dispositions WHERE id=%s",
            (disposition_id,),
        )
        deposit_id = UUID(str(row[0]))
        reservation_id = None if row[1] is None else UUID(str(row[1]))
        current = self.get(deposit_id)
        if reservation_id is not None:
            # V1-056 slice 3b: a Reservation outcome correction is a draft (BR-AUTH-010).
            raise ReservationDepositDraftRequired(
                "Reservation outcome corrections are recorded as drafts"
            )
        if replacement_disposition_id is not None or expected_reservation_version is not None:
            raise DepositResourceInvalid(
                "Lease disposition reversal does not accept Reservation replacement evidence"
            )
        return self._service(current.property_id, actor).reverse_disposition(command, actor=actor)

    def record_departure(
        self, lease_id: UUID, command: RecordPetDepartureCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        current = self.get(command.deposit_id)
        if current.lease_id != lease_id:
            raise DepositResourceNotFound
        return self._service(current.property_id, actor).record_pet_departure(command, actor=actor)

    def qualify_review(
        self,
        departure_id: UUID,
        command: QualifyPetDepositRefundReviewCommand,
        *,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot:
        if departure_id != command.departure_id:
            raise DepositResourceInvalid
        row = self._fetchone(
            "SELECT unit.property_id FROM app.lease_pet_departures AS departure "
            "JOIN app.leases AS lease ON lease.id=departure.lease_id "
            "JOIN app.units AS unit ON unit.id=lease.unit_id "
            "JOIN app.deposits AS deposit ON deposit.id=%s "
            "AND deposit.lease_id=lease.id "
            "AND deposit.pet_approval_id=departure.pet_approval_id "
            "WHERE departure.id=%s",
            (command.deposit_id, departure_id),
        )
        return self._service(UUID(str(row[0])), actor).qualify_pet_refund_review(
            command, actor=actor
        )

    def departures(self, lease_id: UUID) -> tuple[PetDepartureResource, ...]:
        return tuple(
            PetDepartureResource(
                UUID(str(row[0])),
                UUID(str(row[1])),
                lease_id,
                UUID(str(row[2])),
                cast(date, row[3]),
                str(row[4]),
                cast(datetime, row[5]),
                UUID(str(row[6])),
                None if row[7] is None else UUID(str(row[7])),
            )
            for row in self._fetchall(
                "SELECT departure.id,deposit.id,departure.pet_approval_id,"
                "departure.permanently_left_date,departure.reason,departure.occurred_at,"
                "departure.actor_id,review.id FROM app.lease_pet_departures AS departure "
                "JOIN app.deposits AS deposit ON deposit.pet_approval_id=departure.pet_approval_id "
                "LEFT JOIN app.pet_deposit_refund_reviews AS review "
                "ON review.pet_departure_id=departure.id WHERE departure.lease_id=%s "
                "ORDER BY departure.occurred_at DESC,departure.id DESC LIMIT 50",
                (lease_id,),
            )
        )

    def review(self, review_id: UUID) -> PetRefundReviewResource:
        row = self._fetchone(
            "SELECT * FROM app.pet_refund_review_resource_snapshot(%s)",
            (review_id,),
        )
        return PetRefundReviewResource(
            UUID(str(row[0])),
            UUID(str(row[1])),
            UUID(str(row[2])),
            int(str(row[3])),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            cast(datetime, row[7]),
            UUID(str(row[8])),
            str(row[9]),
            int(str(row[10])),
            int(str(row[11])),
        )


class PetDepositCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deposit_id: UUID
    pet_approval_id: UUID
    required_usd_cents: Annotated[int, Field(gt=0)]
    required_effective_date: date
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class SecurityDepositCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deposit_id: UUID
    required_usd_cents: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class DepositReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: UUID
    payment_id: UUID
    amount_usd_cents: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class SecurityDepositReceive(BaseModel):
    """V1-061 (DL-112): Receive Security Deposit in one request. ``required_usd_cents`` is given
    only to make a walk-in Lease's Security Deposit; ``deposit_id`` is then its new id, otherwise
    the Lease's own Security Deposit."""

    model_config = ConfigDict(extra="forbid")
    deposit_id: UUID
    required_usd_cents: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)] | None = None
    receipt_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    payment: OwnMoneyInput


class ReversalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reversal_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_reference: Annotated[str | None, Field(max_length=500)] = None


class DispositionCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reversal_id: UUID
    replacement_disposition_id: UUID | None = None
    expected_reservation_version: Annotated[int | None, Field(ge=1)] = None
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=500)]


class PetDepartureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    departure_id: UUID
    deposit_id: UUID
    permanently_left_date: date
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class PetRefundReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: UUID
    deposit_id: UUID
    obligations_reviewed_usd_cents: Annotated[int, Field(ge=0)]
    review_findings: Annotated[str, Field(min_length=1, max_length=1000)]
    resolution_reference: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


def _require_actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _require(actor: AuthenticatedActor, property_id: UUID, capability: str) -> None:
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _translate(exc: Exception) -> Exception:
    if isinstance(exc, DepositIdempotencyKeyReused):
        return exc
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(
        exc,
        (
            ReservationDepositDraftRequired,
            LeaseDepositDraftRequired,
            DepositReceiptReversalDraftRequired,
        ),
    ):
        return exc
    if isinstance(exc, (DepositResourceNotFound, DepositNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, DepositConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, ReservationVersionConflictError):
        return HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    if isinstance(exc, ReservationCommandConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, (DepositInvalidError, DepositResourceInvalid, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, ReservationCommandInvalidError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, ReservationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, DepositAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, ReservationAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, (DepositResourceUnavailable, DepositServiceUnavailableError)):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(exc, ReservationServiceUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def _named(exc: Exception, refusals: dict[str, Refusal]) -> Exception:
    """A named business-state refusal answers its own code (slice 11c-4); others as before."""
    refusal = database_refusal(exc, refusals)
    return _translate(exc) if refusal is None else RefusedRequest(refusal)


def _snapshot_body(value: DepositSnapshot, actor: AuthenticatedActor) -> dict[str, object]:
    result = asdict(value)
    result.update(
        {
            "deposit_id": str(value.deposit_id),
            "property_id": str(value.property_id),
            "customer_id": str(value.customer_id),
            "reservation_id": None if value.reservation_id is None else str(value.reservation_id),
            "lease_id": None if value.lease_id is None else str(value.lease_id),
            "pet_approval_id": (
                None if value.pet_approval_id is None else str(value.pet_approval_id)
            ),
            "can_manage": is_authorized(
                actor,
                AuthorizationRequirement(
                    capability=DEPOSIT_MANAGE_CAPABILITY, property_id=str(value.property_id)
                ),
            ),
            # A receipt reversal is a draft (owner answer to Q-2026-10-05-22, sub-slice 8r);
            # no one-call reverse route is offered.
            "can_reverse_receipt": False,
            "can_qualify_pet_refund": is_authorized(
                actor,
                AuthorizationRequirement(
                    capability=DEPOSIT_REFUND_QUALIFY_CAPABILITY,
                    property_id=str(value.property_id),
                ),
            ),
            "new_receipt_creation_deferred": True,
            "final_settlement_disposition_deferred": True,
        }
    )
    return result


def _ledger_body(
    value: DepositLedgerEvent, actor: AuthenticatedActor, property_id: UUID
) -> dict[str, object]:
    result = asdict(value)
    result.pop("reversal_eligible")
    # A Reservation disposition is corrected only through a correction draft (V1-056 3b); a
    # Lease forfeiture reversal is a draft (Q-2026-10-04-13, slice 6b) and so is a receipt
    # reversal (Q-2026-10-05-22, sub-slice 8r), so no event offers a one-call reverse route.
    result["can_reverse"] = False
    return result


def create_deposit_router(
    resolver: ActorResolver, flow: DepositResourceFlow, settings: Settings
) -> APIRouter:
    """Create corrected V1-038 Deposit resource and qualification routes."""
    router = APIRouter(prefix="/api/v1", tags=["deposits"])

    def readable(actor: AuthenticatedActor, resource: DepositSnapshot) -> None:
        _require(actor, resource.property_id, DEPOSIT_READ_CAPABILITY)

    @router.get("/reservations/{reservation_id}/deposits")
    def reservation_deposits(
        reservation_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_reservation(reservation_id)
            _require(actor, property_id, DEPOSIT_READ_CAPABILITY)
            values = flow.list_for_reservation(reservation_id)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": [_snapshot_body(value, actor) for value in values],
            "page": {"next_cursor": None, "limit": 10},
            "meta": {
                "request_id": request.state.request_id,
                "can_manage": is_authorized(
                    actor,
                    AuthorizationRequirement(
                        capability=DEPOSIT_MANAGE_CAPABILITY, property_id=str(property_id)
                    ),
                ),
            },
        }

    @router.get("/leases/{lease_id}/deposits")
    def lease_deposits(lease_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_lease(lease_id)
            _require(actor, property_id, DEPOSIT_READ_CAPABILITY)
            values = flow.list_for_lease(lease_id)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": [_snapshot_body(value, actor) for value in values],
            "page": {"next_cursor": None, "limit": 10},
            "meta": {
                "request_id": request.state.request_id,
                "can_manage": is_authorized(
                    actor,
                    AuthorizationRequirement(
                        capability=DEPOSIT_MANAGE_CAPABILITY, property_id=str(property_id)
                    ),
                ),
            },
        }

    @router.get("/deposits/{deposit_id}")
    def deposit(deposit_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            value = flow.get(deposit_id)
            readable(actor, value)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{value.version}"'
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _snapshot_body(value, actor),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/deposits/{deposit_id}/ledger")
    def ledger(
        deposit_id: UUID,
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=MAX_LEDGER_PAGE_SIZE)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(deposit_id)
            readable(actor, resource)
            page = flow.ledger(deposit_id, limit=limit, cursor=cursor)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": [_ledger_body(item, actor, resource.property_id) for item in page.items],
            "page": {"next_cursor": page.next_cursor, "limit": limit},
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/pet-deposits", status_code=status.HTTP_201_CREATED)
    def create_pet_deposit_route(
        lease_id: UUID,
        source: PetDepositCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_lease(lease_id)
            _require(actor, property_id, DEPOSIT_MANAGE_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.create_pet_deposit(
                property_id,
                CreatePetDepositCommand(
                    idempotency_key,
                    source.deposit_id,
                    lease_id,
                    source.pet_approval_id,
                    source.required_usd_cents,
                    source.required_effective_date,
                    source.reason,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Location"] = f"/api/v1/deposits/{value.deposit_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _snapshot_body(value, actor),
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/security-deposit", status_code=status.HTTP_201_CREATED)
    def create_security_deposit_route(
        lease_id: UUID,
        source: SecurityDepositCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """A walk-in Lease's Security Deposit (V1-056 slice 11c-4; Q-2026-10-17-124 point 1)."""
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_lease(lease_id)
            _require(actor, property_id, DEPOSIT_MANAGE_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.create_lease_security_deposit(
                property_id,
                CreateLeaseSecurityDepositCommand(
                    idempotency_key,
                    source.deposit_id,
                    lease_id,
                    source.required_usd_cents,
                    source.reason,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _named(exc, SECURITY_DEPOSIT_REFUSALS) from exc
        response.headers["Location"] = f"/api/v1/deposits/{value.deposit_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _snapshot_body(value, actor),
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/security-deposit/receive", status_code=status.HTTP_201_CREATED)
    def receive_security_deposit_route(
        lease_id: UUID,
        source: SecurityDepositReceive,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """V1-061 (DL-112): the money, its Receipt, a walk-in Lease's Security Deposit and the
        money going into it, saved in one database transaction or not at all."""
        actor = _require_actor(request, resolver)
        for header in ("Idempotency-Key", "Origin", "X-CSRF-Token"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        refusals = {**SECURITY_DEPOSIT_REFUSALS, **DEPOSIT_RECEIPT_REFUSALS}
        try:
            property_id, payer = flow.lease_payer(lease_id)
            _require(actor, property_id, PAYMENT_RECORD_CAPABILITY)
            _require(actor, property_id, PAYMENT_ALLOCATE_CAPABILITY)
            if source.required_usd_cents is not None:
                _require(actor, property_id, DEPOSIT_MANAGE_CAPABILITY)
            require_browser_mutation(request, settings)
            if idempotency_key.int == 0 or source.reason != source.reason.strip():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
            security = next(
                (
                    deposit
                    for deposit in flow.list_for_lease(lease_id)
                    if deposit.deposit_type == "SECURITY"
                ),
                None,
            )
            # The same press again names the Security Deposit it made: its steps answer again.
            if (
                source.required_usd_cents is not None
                and security is not None
                and security.deposit_id != source.deposit_id
            ):
                raise RefusedRequest(DEPOSIT_SECURITY_ALREADY_EXISTS)
            if source.required_usd_cents is None and (
                security is None or security.deposit_id != source.deposit_id
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT)
            scope = f"{property_id}:{actor.actor_id}:{idempotency_key}"
            create = (
                None
                if source.required_usd_cents is None
                else CreateLeaseSecurityDepositCommand(
                    uuid5(ONE_STEP_NAMESPACE, f"deposit-create:{scope}"),
                    source.deposit_id,
                    lease_id,
                    source.required_usd_cents,
                    source.reason,
                )
            )
            # The real Payment replaces this placeholder inside the transaction.
            receipt = RecordDepositReceiptCommand(
                idempotency_key,
                source.receipt_id,
                source.deposit_id,
                idempotency_key,
                source.payment.amount.minor_units,
                source.reason,
            )
            bind_financial_property(request, property_id)
            value, confirmed = flow.receive_with_payment(
                property_id,
                lease_id,
                source.payment.intent(idempotency_key, payer),
                create,
                receipt,
                actor=actor,
            )
        except (HTTPException, RefusedRequest):
            raise
        except Exception as exc:
            raise _named(exc, refusals) from exc
        given = confirmed.get("receipt")
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": {
                "deposit_receipt_id": str(value.deposit_receipt_id),
                "deposit_id": str(value.deposit.deposit_id),
                "payment_id": str(value.payment_id),
                "receipt_number": (
                    cast(dict[str, object], given).get("receipt_number")
                    if isinstance(given, dict)
                    else None
                ),
                "amount_usd_cents": value.amount_usd_cents,
                "required_usd_cents": value.deposit.required_usd_cents,
                "outstanding_required_usd_cents": value.deposit.outstanding_required_usd_cents,
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/deposits/{deposit_id}/receipts", status_code=status.HTTP_201_CREATED)
    def record_receipt_route(
        deposit_id: UUID,
        source: DepositReceiptCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """A receipt from a received Payment into an existing Deposit (V1-056 slice 11c-4;
        Q-2026-10-12-92: payments.allocate, no draft). The answer carries the receipt and the
        Deposit's money only, not the Deposit resource: a holder of payments.allocate alone may
        not read Deposits (decided by Claude under the owner's 2026-10-23 22:30 rule)."""
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.get(deposit_id).property_id
            _require(actor, property_id, PAYMENT_ALLOCATE_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.record_receipt(
                property_id,
                RecordDepositReceiptCommand(
                    idempotency_key,
                    source.receipt_id,
                    deposit_id,
                    source.payment_id,
                    source.amount_usd_cents,
                    source.reason,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _named(exc, DEPOSIT_RECEIPT_REFUSALS) from exc
        # No Location: a holder of payments.allocate alone may not read the Deposit (round 1).
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": {
                "deposit_receipt_id": str(value.deposit_receipt_id),
                "deposit_id": str(value.deposit.deposit_id),
                "payment_id": str(value.payment_id),
                "amount_usd_cents": value.amount_usd_cents,
                "occurred_at": value.occurred_at.isoformat(),
                "payment_available_usd_cents": value.payment_available_usd_cents,
                "required_usd_cents": value.deposit.required_usd_cents,
                "held_refundable_usd_cents": value.deposit.held_refundable_usd_cents,
                "outstanding_required_usd_cents": value.deposit.outstanding_required_usd_cents,
                "version": value.deposit.version,
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/deposit-receipts/{receipt_id}/reverse")
    def reverse_receipt_route(
        receipt_id: UUID,
        source: ReversalCreate,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_receipt(receipt_id)
            _require(actor, property_id, DEPOSIT_CORRECT_CAPABILITY)
            require_browser_mutation(request, settings)
            # V1-056 sub-slice 8r (Q-2026-10-05-22): a receipt reversal is a draft.
            raise DepositReceiptReversalDraftRequired("Deposit receipt reversal draft required")
        except Exception as exc:
            raise _translate(exc) from exc

    @router.post("/deposit-dispositions/{disposition_id}/reverse")
    def reverse_disposition_route(
        disposition_id: UUID,
        source: DispositionCorrectionCreate,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id, reservation_id = flow.disposition_context(disposition_id)
            if reservation_id is None:
                _require(actor, property_id, DEPOSIT_CORRECT_CAPABILITY)
            else:
                _require(actor, property_id, DEPOSIT_OUTCOME_CORRECT_CAPABILITY)
                _require(actor, property_id, RESERVATION_DEPOSIT_DISPOSITION_CAPABILITY)
            require_browser_mutation(request, settings)
            if reservation_id is not None:
                raise ReservationDepositDraftRequired
            # V1-056 slice 6 (Q-2026-10-04-13): a Lease forfeiture reversal is a draft (slice 6b).
            raise LeaseDepositDraftRequired("Lease Deposit forfeiture reversal draft required")
        except Exception as exc:
            raise _translate(exc) from exc

    @router.post("/leases/{lease_id}/pet-departures", status_code=status.HTTP_201_CREATED)
    def record_departure_route(
        lease_id: UUID,
        source: PetDepartureCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_lease(lease_id)
            _require(actor, property_id, DEPOSIT_REFUND_QUALIFY_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.record_departure(
                lease_id,
                RecordPetDepartureCommand(
                    idempotency_key,
                    source.departure_id,
                    source.deposit_id,
                    source.permanently_left_date,
                    source.reason,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Location"] = (
            f"/api/v1/leases/{lease_id}/pet-departures#departure-{source.departure_id}"
        )
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _snapshot_body(value, actor),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/leases/{lease_id}/pet-departures")
    def list_departures(lease_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_lease(lease_id)
            _require(actor, property_id, DEPOSIT_READ_CAPABILITY)
            values = flow.departures(lease_id)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": [asdict(value) for value in values],
            "page": {"next_cursor": None, "limit": 50},
            "meta": {"request_id": request.state.request_id},
        }

    @router.post(
        "/pet-departures/{departure_id}/refund-review", status_code=status.HTTP_201_CREATED
    )
    def qualify_review_route(
        departure_id: UUID,
        source: PetRefundReviewCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_departure(departure_id)
            _require(actor, property_id, DEPOSIT_REFUND_QUALIFY_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.qualify_review(
                departure_id,
                QualifyPetDepositRefundReviewCommand(
                    idempotency_key,
                    source.review_id,
                    departure_id,
                    source.deposit_id,
                    source.obligations_reviewed_usd_cents,
                    source.review_findings,
                    source.resolution_reference,
                    source.reason,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Location"] = f"/api/v1/pet-deposit-refund-reviews/{source.review_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": _snapshot_body(value, actor),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/pet-deposit-refund-reviews/{review_id}")
    def get_review(review_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_review(review_id)
            _require(actor, property_id, DEPOSIT_READ_CAPABILITY)
            value = flow.review(review_id)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": asdict(value), "meta": {"request_id": request.state.request_id}}

    return router
