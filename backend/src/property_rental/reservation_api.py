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

from property_rental.access_control import RENT_BELOW_DEFAULT_CAPABILITY
from property_rental.api_refusals import RENT_BELOW_UNIT_DEFAULT, RefusedRequest
from property_rental.browser_security import require_browser_mutation
from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
)
from property_rental.financial_context import bind_financial_property
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import OwnMoneyInput
from property_rental.refund import RefundMethodChoice
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    PostgresReservationService,
    ReservationAuthorizationError,
    ReservationCancelCommand,
    ReservationCommandConflictError,
    ReservationCommandInvalidError,
    ReservationCreateCommand,
    ReservationDepositDraftRequired,
    ReservationExtendCommand,
    ReservationIdempotencyKeyReused,
    ReservationNotFoundError,
    ReservationStatus,
    ReservationVersionConflictError,
)
from property_rental.reservation_deposit_draft import (
    DECISION_CAPABILITIES,
    DEPOSIT_OUTCOME_CORRECT_CAPABILITY,
    FINANCIAL_APPROVE_CAPABILITY,
    RecordReservationDepositCorrectionDraftCommand,
    RecordReservationDepositDraftCommand,
    ReservationDepositDecision,
    ReservationDepositDecisionPage,
    ReservationDepositDraftAuthorizationError,
    ReservationDepositDraftConflictError,
    ReservationDepositDraftInvalidError,
    ReservationDepositDraftKeyReused,
    ReservationDepositDraftNotFoundError,
    ReservationDepositDraftService,
)
from property_rental.settings import Settings

RESERVATION_READ_CAPABILITY: Final = "reservations.read"
RESERVATION_CREATE_CAPABILITY: Final = "reservations.create"
PAYMENT_RECORD_CAPABILITY: Final = "payments.record"
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

    def unit_default_rent(self, unit_id: UUID) -> int | None:
        """The Unit's default Rent (V1-061, DL-110), or None when it has none."""
        ...

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource: ...

    def create_with_payment(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        payment: dict[str, object],
        *,
        actor: AuthenticatedActor,
    ) -> tuple[ReservationResource, dict[str, object]]:
        """V1-061 (DL-112): the deposit's Payment and the Reservation in one transaction."""
        ...

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

    def record_deposit_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def record_deposit_correction_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositCorrectionDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def confirm_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def decide_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        withdraw_as: ReservationDepositDecision | None,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def awaiting_deposit_decisions(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: ReservationDepositDecisionPage,
    ) -> dict[str, object]: ...


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

    def unit_default_rent(self, unit_id: UUID) -> int | None:
        del unit_id
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

    def create_with_payment(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        payment: dict[str, object],
        *,
        actor: AuthenticatedActor,
    ) -> tuple[ReservationResource, dict[str, object]]:
        del property_id, command, payment, actor
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

    def record_deposit_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, decision, command, actor
        self._raise()
        raise AssertionError

    def record_deposit_correction_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositCorrectionDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, decision, command, actor
        self._raise()
        raise AssertionError

    def confirm_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, reservation_id, draft_id, actor
        self._raise()
        raise AssertionError

    def decide_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        withdraw_as: ReservationDepositDecision | None,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, reservation_id, draft_id, reason, withdraw_as, actor
        self._raise()
        raise AssertionError

    def awaiting_deposit_decisions(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: ReservationDepositDecisionPage,
    ) -> dict[str, object]:
        del property_id, actor, page
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
               reservation.version, deposit.id,
               -- V1-056 sub-slice 10e-2b-4f: the required total with its adjustments.
               (app.deposit_snapshot(deposit.id)->>'required_usd_cents')::bigint,
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
                 WHEN reservation.status = 'CANCELLED'
                  AND NOT EXISTS (SELECT 1 FROM app.deposit_dispositions AS any_disposition
                                  WHERE any_disposition.deposit_id=deposit.id)
                  AND NOT EXISTS (SELECT 1 FROM app.refunds AS any_refund
                                  WHERE any_refund.source_deposit_id=deposit.id)
                  AND EXISTS (SELECT 1 FROM app.deposit_receipts AS held_receipt
                              WHERE held_receipt.deposit_id=deposit.id AND NOT EXISTS (
                                SELECT 1 FROM app.deposit_receipt_reversals AS held_reversal
                                WHERE held_reversal.deposit_receipt_id=held_receipt.id))
                   THEN 'AWAITING_DECISION'
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
          -- V1-056 sub-slice 10e-2b-4c (review round 2): a reversed receipt is not received.
          AND NOT EXISTS (SELECT 1 FROM app.deposit_receipt_reversals AS reversal
                          WHERE reversal.deposit_receipt_id = receipt.id)
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

    def _drafts(self) -> ReservationDepositDraftService:
        if self._financial_database_url is None:
            raise ReservationAuthorizationError(
                "Dedicated Reservation financial persistence is unavailable"
            )
        return ReservationDepositDraftService(self._database_url, self._financial_database_url)

    def record_deposit_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._drafts().record(property_id, decision, command, actor=actor)

    def record_deposit_correction_draft(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositCorrectionDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._drafts().record_correction(property_id, decision, command, actor=actor)

    def confirm_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._drafts().confirm(property_id, reservation_id, draft_id, actor=actor)

    def decide_deposit_draft(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        withdraw_as: ReservationDepositDecision | None,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Reject (``withdraw_as`` None) or withdraw a Reservation Deposit draft."""
        if withdraw_as is None:
            return self._drafts().reject(property_id, reservation_id, draft_id, reason, actor=actor)
        return self._drafts().withdraw(
            property_id, reservation_id, withdraw_as, draft_id, reason, actor=actor
        )

    def awaiting_deposit_decisions(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: ReservationDepositDecisionPage,
    ) -> dict[str, object]:
        return ReservationDepositDraftService(
            self._database_url, self._financial_database_url or self._database_url
        ).awaiting(property_id, actor=actor, page=page)

    def unit_default_rent(self, unit_id: UUID) -> int | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT default_monthly_rent_usd_cents FROM app.units WHERE id = %s",
                    (unit_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ReservationResourceUnavailable from exc
        return None if row is None or row[0] is None else int(str(row[0]))

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        self._service(property_id, actor).create(command)
        return self.get(command.reservation_id)

    def create_with_payment(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        payment: dict[str, object],
        *,
        actor: AuthenticatedActor,
    ) -> tuple[ReservationResource, dict[str, object]]:
        _, confirmed = self._service(property_id, actor).create_with_payment(command, payment)
        return self.get(command.reservation_id), confirmed

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


class ReservationWithPayment(BaseModel):
    """V1-061 (DL-112): Make Reservation with the deposit received, in one request."""

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
    payment: OwnMoneyInput


class ReservationExtend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_id: UUID
    new_expiration_date: date
    reason_memo: Annotated[str, Field(max_length=500)] = ""


class ReservationCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    reason_code: Annotated[str, Field(min_length=1, max_length=100)]
    responsibility: CancellationResponsibility
    property_could_provide_unit: bool
    reason_memo: Annotated[str, Field(max_length=500)] = ""
    coordination_reference: Annotated[str | None, Field(max_length=255)] = None


class RetiredSecurityDepositDisposition(BaseModel):
    """The earlier atomic cancellation body; the route records nothing now."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    outcome_id: UUID
    reason_code: Annotated[str, Field(min_length=1, max_length=100)]
    responsibility: CancellationResponsibility
    property_could_provide_unit: bool
    reason_memo: Annotated[str, Field(max_length=500)] = ""
    coordination_reference: Annotated[str | None, Field(max_length=255)] = None
    refund_number: Annotated[str | None, Field(max_length=100)] = None


class ReservationDepositDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    refund_method_id: UUID | None = None
    reference_note: Annotated[str | None, Field(min_length=1, max_length=500)] = None


class ReservationDepositDraftDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class ReservationDepositCorrectionDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_outcome_id: UUID
    correction_id: UUID
    replacement_outcome_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=500)]
    refund_method_id: UUID | None = None
    reference_note: Annotated[str | None, Field(min_length=1, max_length=500)] = None


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


def _encode_decision_cursor(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    raw = json.dumps([str(value["cancelled_at"]), str(value["reservation_id"])]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_decision_cursor(value: str | None) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        return datetime.fromisoformat(str(decoded[0])), UUID(str(decoded[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ReservationResourceInvalid("cursor is invalid") from exc


def _decision(resource: ReservationResource) -> ReservationDepositDecision:
    """The draft kind follows the cancellation responsibility (BR-RES-021, BR-RES-022)."""
    if resource.cancellation_responsibility is CancellationResponsibility.CUSTOMER:
        return ReservationDepositDecision.DEPOSIT_FORFEITURE
    if resource.cancellation_responsibility is CancellationResponsibility.PROPERTY:
        return ReservationDepositDecision.REFUND
    raise ReservationResourceInvalid("Reservation is not cancelled")


def _method(refund_method_id: UUID | None, reference_note: str | None) -> RefundMethodChoice | None:
    if refund_method_id is None and reference_note is None:
        return None
    if refund_method_id is None or reference_note is None:
        raise ReservationResourceInvalid("Refund method and reference note go together")
    return RefundMethodChoice(refund_method_id, reference_note)


def _translate(exc: Exception) -> Exception:
    if isinstance(
        exc,
        (
            HTTPException,
            ReservationDepositDraftRequired,
            ReservationIdempotencyKeyReused,
            ReservationDepositDraftKeyReused,
        ),
    ):
        return exc
    if isinstance(
        exc,
        (
            ReservationResourceNotFound,
            ReservationNotFoundError,
            ReservationDepositDraftNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, ReservationDepositDraftConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, ReservationDepositDraftInvalidError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, ReservationDepositDraftAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
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

    def create_command(
        actor: AuthenticatedActor,
        property_id: UUID,
        source: ReservationCreate | ReservationWithPayment,
        idempotency_key: UUID,
        payment_id: UUID,
    ) -> ReservationCreateCommand:
        """The Reservation command and the rights it needs, for both create routes."""
        suggested = (source.agreed_monthly_rent_usd_cents + 2) // 5
        acceptance_kind = (
            "NORMAL_SUGGESTION"
            if source.accepted_initial_deposit_usd_cents == suggested
            else "AUTHORIZED_VARIANCE"
        )
        # DL-099 (owner 2026-10-27): only an amount below the suggestion needs the override; more
        # is still recorded as a variance with its reason, under reservations.create.
        below = source.accepted_initial_deposit_usd_cents < suggested
        if below:
            _require(actor, property_id, DEPOSIT_OVERRIDE_CAPABILITY)
        # V1-061 (owner 2026-10-29, DL-110): a Rent below the Unit's default Rent needs a
        # Manager or the Owner; the acceptance reason says why.
        if not _can(actor, property_id, RENT_BELOW_DEFAULT_CAPABILITY):
            try:
                floor = flow.unit_default_rent(source.unit_id)
            except Exception as exc:
                raise _translate(exc) from exc
            if floor is not None and source.agreed_monthly_rent_usd_cents < floor:
                raise RefusedRequest(RENT_BELOW_UNIT_DEFAULT)
        return ReservationCreateCommand(
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
            accepted_at=None,
            acceptance_reason=source.acceptance_reason,
            authorization_reference=(
                DEPOSIT_OVERRIDE_CAPABILITY if below else RESERVATION_CREATE_CAPABILITY
            ),
            calculation_trace={
                "agreed_monthly_rent_usd_cents": source.agreed_monthly_rent_usd_cents,
                "suggested_rate_basis_points": 2000,
                "suggested_amount_usd_cents": suggested,
            },
            deposit_id=source.deposit_id,
            required_deposit_usd_cents=source.required_security_deposit_usd_cents,
            receipt_id=source.receipt_id,
            payment_id=payment_id,
            # Owner answer (a) to Q-2026-10-20-147: the database's statement time.
            received_at=None,
        )

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
        command = create_command(actor, property_id, source, idempotency_key, source.payment_id)
        try:
            resource = flow.create(property_id, command, actor=actor)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/reservations/{resource.reservation_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/properties/{property_id}/reservations/with-payment",
        status_code=status.HTTP_201_CREATED,
    )
    def create_reservation_with_payment(
        property_id: UUID,
        source: ReservationWithPayment,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """V1-061 (DL-112): Make Reservation in one press. The deposit received, its Receipt and
        the Reservation that holds it are saved in one database transaction, or nothing is."""
        actor = _require_actor(request, resolver)
        for header in ("Idempotency-Key", "Origin", "X-CSRF-Token"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        _require(actor, property_id, RESERVATION_CREATE_CAPABILITY)
        _require(actor, property_id, PAYMENT_RECORD_CAPABILITY)
        require_browser_mutation(request, settings)
        if idempotency_key.int == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if source.payment.amount.minor_units != source.accepted_initial_deposit_usd_cents:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        bind_financial_property(request, property_id)
        # The real Payment replaces this placeholder inside the transaction.
        command = create_command(actor, property_id, source, idempotency_key, idempotency_key)
        try:
            payment = source.payment.intent(idempotency_key, source.customer_id)
            resource, confirmed = flow.create_with_payment(
                property_id, command, payment, actor=actor
            )
        except Exception as exc:
            raise _translate(exc) from exc
        receipt = confirmed.get("receipt")
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/reservations/{resource.reservation_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": {
                **_body(resource, actor),
                "payment_id": str(cast(dict[str, object], confirmed["payment"])["id"]),
                "receipt_number": (
                    cast(dict[str, object], receipt).get("receipt_number")
                    if isinstance(receipt, dict)
                    else None
                ),
            },
            "meta": {"request_id": request.state.request_id},
        }

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
                    # The database's own time at the command (Q-2026-10-14-112).
                    approved_at=None,
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
            resource = flow.cancel(
                ReservationCancelCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    reservation_id=reservation_id,
                    expected_version=_version(if_match),
                    reason_code=source.reason_code,
                    responsibility=source.responsibility,
                    property_could_provide_unit=source.property_could_provide_unit,
                    reason_memo=source.reason_memo,
                    coordination_reference=source.coordination_reference,
                    authorization_reference=RESERVATION_CANCEL_CAPABILITY,
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
        source: RetiredSecurityDepositDisposition,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Retired (V1-056 slice 3b): the Deposit outcome is a draft; this records nothing."""
        del source, idempotency_key
        actor = _require_actor(request, resolver)
        try:
            property_id = flow.property_for_security_deposit_disposition(reservation_id)
            _require(actor, property_id, RESERVATION_CANCEL_CAPABILITY)
            _require(actor, property_id, "reservation_deposits.dispose")
            require_browser_mutation(request, settings)
        except Exception as exc:
            raise _translate(exc) from exc
        raise ReservationDepositDraftRequired

    @router.get("/properties/{property_id}/reservation-deposit-decisions")
    def list_reservation_deposit_decisions(
        property_id: UUID,
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        """Reservations waiting for a Deposit decision (owner answer, 2026-10-04)."""
        actor = _require_actor(request, resolver)
        _require(actor, property_id, RESERVATION_READ_CAPABILITY)
        try:
            after_cancelled_at, after_id = _decode_decision_cursor(cursor)
            page = ReservationDepositDecisionPage(limit, after_cancelled_at, after_id)
            value = flow.awaiting_deposit_decisions(property_id, actor=actor, page=page)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"
        return {
            "data": {
                "items": value.get("items", []),
                "next_cursor": _encode_decision_cursor(value.get("next_after")),
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post(
        "/reservations/{reservation_id}/deposit-drafts", status_code=status.HTTP_201_CREATED
    )
    def create_reservation_deposit_draft(
        reservation_id: UUID,
        source: ReservationDepositDraftCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Record the Deposit Refund or forfeiture draft (BR-AUTH-010); no effect yet."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_READ_CAPABILITY)
            decision = _decision(current)
            _require(actor, current.property_id, DECISION_CAPABILITIES[decision])
            require_browser_mutation(request, settings)
            draft = flow.record_deposit_draft(
                current.property_id,
                decision,
                RecordReservationDepositDraftCommand(
                    idempotency_key,
                    reservation_id,
                    source.outcome_id,
                    source.reason,
                    _method(source.refund_method_id, source.reference_note),
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": draft, "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/reservations/{reservation_id}/deposit-correction-drafts",
        status_code=status.HTTP_201_CREATED,
    )
    def create_reservation_deposit_correction_draft(
        reservation_id: UUID,
        source: ReservationDepositCorrectionDraftCreate,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Record a draft that replaces the confirmed Deposit outcome; no effect yet."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_READ_CAPABILITY)
            decision = _decision(current)
            _require(actor, current.property_id, DEPOSIT_OUTCOME_CORRECT_CAPABILITY)
            _require(actor, current.property_id, DECISION_CAPABILITIES[decision])
            require_browser_mutation(request, settings)
            draft = flow.record_deposit_correction_draft(
                current.property_id,
                decision,
                RecordReservationDepositCorrectionDraftCommand(
                    idempotency_key,
                    reservation_id,
                    source.expected_outcome_id,
                    source.correction_id,
                    source.replacement_outcome_id,
                    source.reason,
                    source.evidence_reference,
                    _method(source.refund_method_id, source.reference_note),
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": draft, "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/deposit-drafts/{draft_id}/confirm")
    def confirm_reservation_deposit_draft(
        reservation_id: UUID,
        draft_id: UUID,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Apply the draft's outcome; only a financial.approve holder may confirm.

        The draft id is the idempotency identity; the header is required like on every
        financial command but is not stored.
        """
        del idempotency_key
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_READ_CAPABILITY)
            _require(actor, current.property_id, FINANCIAL_APPROVE_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.confirm_deposit_draft(
                current.property_id, reservation_id, draft_id, actor=actor
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": value, "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/deposit-drafts/{draft_id}/reject")
    def reject_reservation_deposit_draft(
        reservation_id: UUID,
        draft_id: UUID,
        source: ReservationDepositDraftDecision,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Reject a pending draft (financial.approve only); it moves no money."""
        del idempotency_key
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_READ_CAPABILITY)
            _require(actor, current.property_id, FINANCIAL_APPROVE_CAPABILITY)
            require_browser_mutation(request, settings)
            value = flow.decide_deposit_draft(
                current.property_id,
                reservation_id,
                draft_id,
                source.reason,
                withdraw_as=None,
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": value, "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/deposit-drafts/{draft_id}/withdraw")
    def withdraw_reservation_deposit_draft(
        reservation_id: UUID,
        draft_id: UUID,
        source: ReservationDepositDraftDecision,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """Withdraw a pending draft (its preparer only); it moves no money."""
        del idempotency_key
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(reservation_id)
            _require(actor, current.property_id, RESERVATION_READ_CAPABILITY)
            decision = _decision(current)
            _require(actor, current.property_id, DECISION_CAPABILITIES[decision])
            require_browser_mutation(request, settings)
            value = flow.decide_deposit_draft(
                current.property_id,
                reservation_id,
                draft_id,
                source.reason,
                withdraw_as=decision,
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": value, "meta": {"request_id": request.state.request_id}}

    return router
