"""Authorized Lease, signer, Occupancy, and move-in HTTP resources."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Annotated, Final, Literal, Protocol, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import RENT_BELOW_DEFAULT_CAPABILITY
from property_rental.api_refusals import (
    LEASE_END_DATE_NOT_MONTH_END,
    LEASE_REQUIRED_SERVICE_MISSING,
    OCCUPANT_LAST_SIGNER,
    OCCUPANT_MOVE_OUT_DATE,
    OCCUPANT_NOT_LIVING_THERE,
    OCCUPANT_PRIMARY_TENANT,
    OCCUPANT_SIGNERS_MUST_AGREE,
    RENT_BELOW_UNIT_DEFAULT,
    Refusal,
    RefusedRequest,
)
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.invoice import INVOICE_READ_CAPABILITY
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LEASE_SIGNER_MANAGE_CAPABILITY,
    LEASE_TERMINATE_CAPABILITY,
    LeaseAddSignerCommand,
    LeaseAuthorizationError,
    LeaseCancelCommand,
    LeaseCommandConflictError,
    LeaseCommandInvalidError,
    LeaseDraftCommand,
    LeaseDraftSigner,
    LeaseEndDateNotMonthEndError,
    LeaseNotFoundError,
    LeasePetTerm,
    LeaseRecordSignatureCommand,
    LeaseRequiredServiceMissingError,
    LeaseServiceTerm,
    LeaseSignCommand,
    LeaseStatus,
    LeaseTerminateCommand,
    LeaseUpdateDraftCommand,
    LeaseVersionConflictError,
    PostgresLeaseService,
)
from property_rental.lease_enforcement import NONPAYMENT_READ
from property_rental.lease_termination import TerminationBasis, TerminationContext
from property_rental.move_in import (
    AddLeaseOccupantCommand,
    CompleteMoveInCommand,
    MoveInAuthorizationError,
    MoveInConflictError,
    MoveInInvalidError,
    MoveInNotFoundError,
    MoveInOccupant,
    MoveInSnapshot,
    MoveInVersionConflictError,
    OccupantMoveOutCommand,
    OccupantMoveOutRefusedError,
    PostgresMoveInService,
    RecordLeaseMoveInCommand,
)
from property_rental.settings import Settings

LEASE_READ_CAPABILITY: Final = "leases.read"
MOVE_IN_CAPABILITY: Final = "reservations.complete"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100
# V1-061 (DL-111): each database reason for refusing one occupant's move-out, by its refusal.
OCCUPANT_MOVE_OUT_REFUSALS: Final[dict[str, Refusal]] = {
    "PRIMARY_TENANT": OCCUPANT_PRIMARY_TENANT,
    "LAST_SIGNER": OCCUPANT_LAST_SIGNER,
    "SIGNERS_AGREE": OCCUPANT_SIGNERS_MUST_AGREE,
    "DATE": OCCUPANT_MOVE_OUT_DATE,
    "NOT_LIVING_THERE": OCCUPANT_NOT_LIVING_THERE,
}
LeasePeriodFilter = Literal["current", "future", "historical", "approaching_end"]


class LeaseResourceNotFound(LookupError):
    """Lease is absent or outside the requested Property scope."""


class LeaseResourceUnavailable(RuntimeError):
    """Lease persistence is unavailable."""


class LeaseResourceInvalid(ValueError):
    """Lease query input or cursor is invalid."""


@dataclass(frozen=True, slots=True)
class LeaseSignerResource:
    signer_id: UUID
    customer_id: UUID
    customer_name: str
    is_primary_tenant: bool
    signed_at: datetime | None
    added_at: datetime


@dataclass(frozen=True, slots=True)
class OccupancyResource:
    occupancy_id: UUID
    customer_id: UUID
    customer_name: str
    move_in_date: date
    move_out_date: date | None
    version: int


@dataclass(frozen=True, slots=True)
class PlannedOccupantResource:
    """A person who moves in with the Lease (the draft's list and Add occupant, DL-102)."""

    customer_id: UUID
    customer_name: str


@dataclass(frozen=True, slots=True)
class LeaseTimelineEvent:
    event_id: UUID
    event_kind: str
    occurred_at: datetime
    reason: str
    actor_id: UUID
    source_reference: str | None
    source_href: str | None


@dataclass(frozen=True, slots=True)
class LeaseTimelineVisibility:
    """Properties where the actor may already see restricted Lease timeline events.

    Initial Rent Due Date overrides need ``invoices.read`` and Rent-nonpayment events need
    ``rent_nonpayment.read``. The application decides the capabilities; the database checks
    the active actor and keeps only the Lease's own Property from each list.
    """

    actor_id: UUID | None = None
    invoice_property_ids: tuple[UUID, ...] = ()
    nonpayment_property_ids: tuple[UUID, ...] = ()

    @property
    def restricted(self) -> bool:
        return self.actor_id is not None and bool(
            self.invoice_property_ids or self.nonpayment_property_ids
        )


NO_RESTRICTED_EVENTS: Final = LeaseTimelineVisibility()


def _granted_properties(actor: AuthenticatedActor, capability: str) -> tuple[UUID, ...]:
    properties: set[UUID] = set()
    for grant in actor.capability_grants:
        if grant.capability != capability:
            continue
        for value in grant.property_ids:
            try:
                parsed = UUID(value)
            except (ValueError, TypeError, AttributeError):
                continue
            if parsed.int and str(parsed) == value:
                properties.add(parsed)
    return tuple(sorted(properties))


def timeline_visibility(actor: AuthenticatedActor) -> LeaseTimelineVisibility:
    invoice_properties = _granted_properties(actor, INVOICE_READ_CAPABILITY)
    nonpayment_properties = _granted_properties(actor, NONPAYMENT_READ)
    if not invoice_properties and not nonpayment_properties:
        return NO_RESTRICTED_EVENTS
    try:
        actor_id = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError):
        return NO_RESTRICTED_EVENTS
    return LeaseTimelineVisibility(actor_id, invoice_properties, nonpayment_properties)


@dataclass(frozen=True, slots=True)
class LeaseServiceTermResource:
    term_id: UUID
    property_service_id: UUID
    service_name: str
    applicable_from: date
    applicable_through: date | None
    service_approval_period_id: UUID
    terms_reference: str


@dataclass(frozen=True, slots=True)
class LeaseResource:
    lease_id: UUID
    property_id: UUID
    unit_id: UUID
    unit_number: str
    primary_tenant_id: UUID
    primary_tenant_name: str
    status: LeaseStatus
    start_date: date | None
    end_date: date | None
    monthly_rent_usd_cents: int | None
    predecessor_lease_id: UUID | None
    signed_at: datetime | None
    terminated_at: datetime | None
    actual_termination_date: date | None
    version: int
    created_at: datetime
    pet_deposit_required: bool
    pet_description: str | None
    security_deposit_id: UUID | None = None
    planned_occupant_customer_ids: tuple[UUID, ...] = ()
    planned_occupants: tuple[PlannedOccupantResource, ...] = ()
    service_terms: tuple[LeaseServiceTermResource, ...] = ()
    signers: tuple[LeaseSignerResource, ...] = ()
    occupancies: tuple[OccupancyResource, ...] = ()
    timeline: tuple[LeaseTimelineEvent, ...] = ()
    timeline_next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class LeasePage:
    items: tuple[LeaseResource, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class LeaseTimelinePage:
    items: tuple[LeaseTimelineEvent, ...]
    next_cursor: str | None


class LeaseResourceFlow(Protocol):
    def list(
        self,
        property_id: UUID,
        *,
        lease_status: LeaseStatus | None,
        unit_id: UUID | None,
        customer_id: UUID | None,
        starts_on_or_after: date | None,
        ends_on_or_before: date | None,
        period: LeasePeriodFilter | None,
        as_of: date | None,
        approaching_days: int,
        limit: int,
        cursor: str | None,
    ) -> LeasePage: ...

    def get(
        self, lease_id: UUID, *, visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS
    ) -> LeaseResource: ...

    def timeline(
        self,
        lease_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS,
    ) -> LeaseTimelinePage: ...

    def draft(
        self,
        property_id: UUID,
        command: LeaseDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource: ...

    def update_draft(
        self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource: ...

    def rent_floor(self, unit_id: UUID, security_deposit_id: UUID | None) -> int | None:
        """The lowest Rent a draft may have without `rent.below_default` (DL-110), or None."""
        ...

    def add_signer(
        self, command: LeaseAddSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource: ...

    def record_signature(
        self, command: LeaseRecordSignatureCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource: ...

    def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseResource: ...

    def terminate(
        self, command: LeaseTerminateCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource: ...

    def complete_move_in(
        self,
        property_id: UUID,
        command: CompleteMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> MoveInSnapshot: ...

    def cancel(
        self, command: LeaseCancelCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource: ...

    def record_move_in(
        self,
        property_id: UUID,
        command: RecordLeaseMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource: ...

    def add_occupant(
        self,
        property_id: UUID,
        command: AddLeaseOccupantCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource: ...

    def move_out_occupant(
        self,
        property_id: UUID,
        command: OccupantMoveOutCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource: ...


class UnavailableLeaseResourceFlow:
    def _raise(self) -> None:
        raise LeaseResourceUnavailable

    def list(
        self,
        property_id: UUID,
        *,
        lease_status: LeaseStatus | None,
        unit_id: UUID | None,
        customer_id: UUID | None,
        starts_on_or_after: date | None,
        ends_on_or_before: date | None,
        period: LeasePeriodFilter | None,
        as_of: date | None,
        approaching_days: int,
        limit: int,
        cursor: str | None,
    ) -> LeasePage:
        del (
            property_id,
            lease_status,
            unit_id,
            customer_id,
            starts_on_or_after,
            ends_on_or_before,
            period,
            as_of,
            approaching_days,
            limit,
            cursor,
        )
        self._raise()
        raise AssertionError

    def get(
        self, lease_id: UUID, *, visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS
    ) -> LeaseResource:
        del lease_id, visibility
        self._raise()
        raise AssertionError

    def rent_floor(self, unit_id: UUID, security_deposit_id: UUID | None) -> int | None:
        del unit_id, security_deposit_id
        self._raise()
        raise AssertionError

    def timeline(
        self,
        lease_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS,
    ) -> LeaseTimelinePage:
        del lease_id, limit, cursor, visibility
        self._raise()
        raise AssertionError

    def draft(
        self,
        property_id: UUID,
        command: LeaseDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, command, actor
        self._raise()
        raise AssertionError

    def update_draft(
        self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def add_signer(
        self, command: LeaseAddSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def record_signature(
        self, command: LeaseRecordSignatureCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def terminate(
        self, command: LeaseTerminateCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def complete_move_in(
        self,
        property_id: UUID,
        command: CompleteMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> MoveInSnapshot:
        del property_id, command, actor
        self._raise()
        raise AssertionError

    def cancel(self, command: LeaseCancelCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        del command, actor
        self._raise()
        raise AssertionError

    def record_move_in(
        self,
        property_id: UUID,
        command: RecordLeaseMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, command, actor
        self._raise()
        raise AssertionError

    def add_occupant(
        self,
        property_id: UUID,
        command: AddLeaseOccupantCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, command, actor
        self._raise()
        raise AssertionError

    def move_out_occupant(
        self,
        property_id: UUID,
        command: OccupantMoveOutCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, command, actor
        self._raise()
        raise AssertionError


def _encode_cursor(created_at: datetime, lease_id: UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(lease_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        created_at = datetime.fromisoformat(str(decoded[0]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, UUID(str(decoded[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise LeaseResourceInvalid("cursor is invalid") from exc


class PostgresLeaseResourceFlow:
    """Bounded Lease queries over the published command services."""

    _select: Final = """
        SELECT lease.id, unit.property_id, lease.unit_id, unit.unit_number,
               lease.primary_tenant_id, customer.legal_name, lease.status,
               lease.start_date, lease.end_date, lease.monthly_rent_usd_cents,
               lease.predecessor_lease_id, lease.signed_at, lease.terminated_at,
               lease.actual_termination_date, lease.version, lease.created_at,
               COALESCE((
                   SELECT approval.deposit_required_by_signed_terms
                   FROM app.lease_pet_approvals AS approval
                   WHERE approval.lease_id = lease.id
                   ORDER BY approval.approved_date DESC, approval.id DESC LIMIT 1
               ), false),
               (
                   SELECT approval.pet_description
                   FROM app.lease_pet_approvals AS approval
                   WHERE approval.lease_id = lease.id
                   ORDER BY approval.approved_date DESC, approval.id DESC LIMIT 1
               )
        FROM app.leases AS lease
        JOIN app.units AS unit ON unit.id = lease.unit_id
        JOIN app.customers AS customer ON customer.id = lease.primary_tenant_id
    """
    _timeline_select: Final = """
        SELECT * FROM (
            SELECT event_id,action AS event_kind,occurred_at,reason,actor_id,
                   COALESCE(governing_event_reference,event_id::text) AS source_reference,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||event_id::text
                       AS source_href
            FROM app.lease_commands WHERE lease_id=%s
            UNION ALL
            SELECT id,'lease.move_in',occurred_at,reason,actor_id,reservation_id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.move_in_events WHERE lease_id=%s
            UNION ALL
            -- V1-060 B6: the move-in of a Lease signed with its outcome record (DL-066).
            SELECT id,'lease.move_in',occurred_at,reason,actor_id,id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.lease_move_ins WHERE lease_id=%s
            UNION ALL
            SELECT id,'lease.occupant_added',occurred_at,reason,actor_id,id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.lease_occupant_additions WHERE lease_id=%s
            UNION ALL
            -- V1-061 (DL-111): one person moved out on their own day.
            SELECT id,'lease.occupant_moved_out',occurred_at,reason,actor_id,id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.lease_occupant_move_outs WHERE lease_id=%s
            UNION ALL
            SELECT id,'lease.termination_notice',occurred_at,notice_text,actor_id,id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.termination_notices WHERE lease_id=%s
            UNION ALL
            SELECT id,'lease.violation_warning',occurred_at,violation_description,actor_id,
                   id::text,'/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.lease_violation_warnings WHERE lease_id=%s
            UNION ALL
            SELECT successor.id,'lease.renewal_successor',successor.created_at,
                   'Successor Lease drafted',successor.created_by,successor.id::text,
                   '/api/v1/leases/'||successor.id::text
            FROM app.leases AS successor WHERE successor.predecessor_lease_id=%s
            UNION ALL
            SELECT id,
                   CASE path WHEN 'NEVER_MOVED_IN' THEN 'lease.unpaid_initial_never_moved_in'
                             ELSE 'lease.unpaid_initial_moved_in_credit' END,
                   occurred_at,reason,actor_id,termination_event_id::text,
                   '/api/v1/leases/'||lease_id::text||'#timeline-'||id::text
            FROM app.unpaid_initial_termination_resolutions WHERE lease_id=%s
        ) AS event
        WHERE (%s::timestamptz IS NULL OR (occurred_at,event_id) > (%s,%s::uuid))
        ORDER BY occurred_at,event_id LIMIT %s
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @staticmethod
    def _resource(row: tuple[object, ...]) -> LeaseResource:
        return LeaseResource(
            lease_id=UUID(str(row[0])),
            property_id=UUID(str(row[1])),
            unit_id=UUID(str(row[2])),
            unit_number=str(row[3]),
            primary_tenant_id=UUID(str(row[4])),
            primary_tenant_name=str(row[5]),
            status=LeaseStatus(str(row[6])),
            start_date=cast(date | None, row[7]),
            end_date=cast(date | None, row[8]),
            monthly_rent_usd_cents=None if row[9] is None else int(str(row[9])),
            predecessor_lease_id=None if row[10] is None else UUID(str(row[10])),
            signed_at=cast(datetime | None, row[11]),
            terminated_at=cast(datetime | None, row[12]),
            actual_termination_date=cast(date | None, row[13]),
            version=int(str(row[14])),
            created_at=cast(datetime, row[15]),
            pet_deposit_required=bool(row[16]),
            pet_description=None if row[17] is None else str(row[17]),
        )

    def _fetch(self, query: str, parameters: tuple[object, ...]) -> list[tuple[object, ...]]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return list(connection.execute(query, parameters).fetchall())
        except psycopg.Error as exc:
            raise LeaseResourceUnavailable from exc

    def list(
        self,
        property_id: UUID,
        *,
        lease_status: LeaseStatus | None,
        unit_id: UUID | None,
        customer_id: UUID | None,
        starts_on_or_after: date | None,
        ends_on_or_before: date | None,
        period: LeasePeriodFilter | None,
        as_of: date | None,
        approaching_days: int,
        limit: int,
        cursor: str | None,
    ) -> LeasePage:
        decoded = _decode_cursor(cursor)
        clauses = ["unit.property_id = %s"]
        parameters: list[object] = [property_id]
        if lease_status is not None:
            clauses.append("lease.status = %s")
            parameters.append(lease_status.value)
        if unit_id is not None:
            clauses.append("lease.unit_id = %s")
            parameters.append(unit_id)
        if customer_id is not None:
            clauses.append("lease.primary_tenant_id = %s")
            parameters.append(customer_id)
        if starts_on_or_after is not None:
            clauses.append("lease.start_date >= %s")
            parameters.append(starts_on_or_after)
        if ends_on_or_before is not None:
            clauses.append("lease.end_date <= %s")
            parameters.append(ends_on_or_before)
        if period is not None:
            if as_of is None:
                raise LeaseResourceInvalid("as_of is required for a period filter")
            if period == "current":
                clauses.append(
                    "lease.status = 'SIGNED' AND lease.start_date <= %s AND lease.end_date >= %s"
                )
                parameters.extend((as_of, as_of))
            elif period == "future":
                clauses.append("lease.start_date > %s")
                parameters.append(as_of)
            elif period == "historical":
                clauses.append(
                    "(lease.end_date < %s OR lease.status IN ('CANCELLED','TERMINATED'))"
                )
                parameters.append(as_of)
            else:
                clauses.append(
                    "lease.status = 'SIGNED' AND lease.end_date BETWEEN %s AND (%s + %s)"
                )
                parameters.extend((as_of, as_of, approaching_days))
        if decoded is not None:
            clauses.append("(lease.created_at, lease.id) < (%s, %s)")
            parameters.extend(decoded)
        parameters.append(limit + 1)
        rows = self._fetch(
            self._select
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY lease.created_at DESC, lease.id DESC LIMIT %s",
            tuple(parameters),
        )
        resources = tuple(self._resource(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and resources:
            last = resources[-1]
            next_cursor = _encode_cursor(last.created_at, last.lease_id)
        return LeasePage(resources, next_cursor)

    @staticmethod
    def _timeline_resource(row: tuple[object, ...]) -> LeaseTimelineEvent:
        return LeaseTimelineEvent(
            event_id=UUID(str(row[0])),
            event_kind=str(row[1]),
            occurred_at=cast(datetime, row[2]),
            reason=str(row[3]),
            actor_id=UUID(str(row[4])),
            source_reference=None if row[5] is None else str(row[5]),
            source_href=None if row[6] is None else str(row[6]),
        )

    def _timeline_page(
        self,
        connection: psycopg.Connection[tuple[object, ...]],
        lease_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS,
    ) -> LeaseTimelinePage:
        decoded = _decode_cursor(cursor)
        cursor_time = None if decoded is None else decoded[0]
        cursor_id = None if decoded is None else decoded[1]
        rows = connection.execute(
            self._timeline_select,
            (
                *(lease_id,) * 9,
                cursor_time,
                cursor_time,
                cursor_id,
                limit + 1,
            ),
        ).fetchall()
        if visibility.restricted:
            # Merge the bounded restricted read into the same (occurred_at, event_id)
            # order, so pages and cursors keep their meaning.
            restricted = connection.execute(
                "SELECT * FROM app.lease_timeline_restricted("
                "%s,%s,%s::uuid[],%s::uuid[],%s::timestamptz,%s::uuid,%s)",
                (
                    visibility.actor_id,
                    lease_id,
                    list(visibility.invoice_property_ids),
                    list(visibility.nonpayment_property_ids),
                    cursor_time,
                    cursor_id,
                    limit + 1,
                ),
            ).fetchall()
            rows = sorted(
                [*rows, *restricted],
                key=lambda row: (cast(datetime, row[2]), UUID(str(row[0]))),
            )[: limit + 1]
        items = tuple(self._timeline_resource(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.occurred_at, last.event_id)
        return LeaseTimelinePage(items, next_cursor)

    def timeline(
        self,
        lease_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS,
    ) -> LeaseTimelinePage:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                return self._timeline_page(
                    connection, lease_id, limit=limit, cursor=cursor, visibility=visibility
                )
        except psycopg.Error as exc:
            raise LeaseResourceUnavailable from exc

    def rent_floor(self, unit_id: UUID, security_deposit_id: UUID | None) -> int | None:
        """The Unit's default Rent (DL-110); a draft from a Booking may keep the Booking's agreed
        Rent, which was agreed when the Booking was made."""
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT unit.default_monthly_rent_usd_cents, ("
                    "SELECT reservation.agreed_monthly_rent_usd_cents "
                    "FROM app.deposits AS deposit JOIN app.reservations AS reservation "
                    "ON reservation.id = deposit.reservation_id "
                    "WHERE deposit.id = %s AND reservation.unit_id = unit.id) "
                    "FROM app.units AS unit WHERE unit.id = %s",
                    (security_deposit_id, unit_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise LeaseResourceUnavailable from exc
        if row is None or row[0] is None:
            return None
        floor = int(str(row[0]))
        if row[1] is not None:
            floor = min(floor, int(str(row[1])))
        return floor

    def get(
        self, lease_id: UUID, *, visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS
    ) -> LeaseResource:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                rows = connection.execute(
                    self._select + " WHERE lease.id = %s", (lease_id,)
                ).fetchall()
                if not rows:
                    raise LeaseResourceNotFound
                resource = self._resource(rows[0])
                signers = tuple(
                    LeaseSignerResource(
                        signer_id=UUID(str(row[0])),
                        customer_id=UUID(str(row[1])),
                        customer_name=str(row[2]),
                        is_primary_tenant=UUID(str(row[1])) == resource.primary_tenant_id,
                        signed_at=cast(datetime | None, row[3]),
                        added_at=cast(datetime, row[4]),
                    )
                    for row in connection.execute(
                        "SELECT signer.id,signer.customer_id,customer.legal_name,"
                        "signer.signed_at,signer.added_at FROM app.lease_signers AS signer "
                        "JOIN app.customers AS customer ON customer.id=signer.customer_id "
                        "WHERE signer.lease_id=%s ORDER BY signer.added_at,signer.id",
                        (lease_id,),
                    ).fetchall()
                )
                occupancies = tuple(
                    OccupancyResource(
                        occupancy_id=UUID(str(row[0])),
                        customer_id=UUID(str(row[1])),
                        customer_name=str(row[2]),
                        move_in_date=cast(date, row[3]),
                        move_out_date=cast(date | None, row[4]),
                        version=int(str(row[5])),
                    )
                    for row in connection.execute(
                        "SELECT occupancy.id,occupancy.customer_id,customer.legal_name,"
                        "occupancy.move_in_date,occupancy.move_out_date,occupancy.version "
                        "FROM app.occupancies AS occupancy JOIN app.customers AS customer "
                        "ON customer.id=occupancy.customer_id WHERE occupancy.lease_id=%s "
                        "ORDER BY occupancy.move_in_date,occupancy.id",
                        (lease_id,),
                    ).fetchall()
                )
                service_terms = tuple(
                    LeaseServiceTermResource(
                        term_id=UUID(str(row[0])),
                        property_service_id=UUID(str(row[1])),
                        service_name=str(row[2]),
                        applicable_from=cast(date, row[3]),
                        applicable_through=cast(date | None, row[4]),
                        service_approval_period_id=UUID(str(row[5])),
                        terms_reference=str(row[6]),
                    )
                    for row in connection.execute(
                        "SELECT term.id,term.property_service_id,service.display_name,"
                        "term.applicable_from,term.applicable_through,"
                        "term.service_approval_period_id,term.terms_reference "
                        "FROM app.lease_service_terms AS term "
                        "JOIN app.property_services AS service "
                        "ON service.id=term.property_service_id "
                        "WHERE term.lease_id=%s ORDER BY term.applicable_from,term.id",
                        (lease_id,),
                    ).fetchall()
                )
                draft_source = connection.execute(
                    "SELECT result_snapshot->'planned_occupant_customer_ids',"
                    "result_snapshot->>'security_deposit_id' "
                    "FROM app.lease_commands WHERE lease_id=%s AND action='lease.draft' "
                    "ORDER BY occurred_at,event_id LIMIT 1",
                    (lease_id,),
                ).fetchone()
                planned_occupants = (
                    ()
                    if draft_source is None or draft_source[0] is None
                    else tuple(UUID(str(value)) for value in cast(list[object], draft_source[0]))
                )
                # V1-060 B6 (DL-102): Add occupant before the move-in plans one more person. A
                # draft that planned nobody meant the Primary Tenant alone (Record move-in ticks
                # the tenant then), so the tenant stays first once someone is added.
                additions = connection.execute(
                    "SELECT customer_id FROM app.lease_occupant_additions "
                    "WHERE lease_id=%s AND occupancy_id IS NULL ORDER BY occurred_at,id",
                    (lease_id,),
                ).fetchall()
                if additions and not planned_occupants:
                    planned_occupants = (resource.primary_tenant_id,)
                for row in additions:
                    added = UUID(str(row[0]))
                    if added not in planned_occupants:
                        planned_occupants = (*planned_occupants, added)
                names = {
                    UUID(str(row[0])): str(row[1])
                    for row in connection.execute(
                        "SELECT id,legal_name FROM app.customers WHERE id = ANY(%s)",
                        (list(planned_occupants),),
                    ).fetchall()
                }
                planned_people = tuple(
                    PlannedOccupantResource(customer_id=value, customer_name=names[value])
                    for value in planned_occupants
                    if value in names
                )
                security_deposit_id = (
                    None
                    if draft_source is None or draft_source[1] is None
                    else UUID(str(draft_source[1]))
                )
                timeline_page = self._timeline_page(
                    connection, lease_id, limit=MAX_PAGE_SIZE, cursor=None, visibility=visibility
                )
        except psycopg.Error as exc:
            raise LeaseResourceUnavailable from exc
        return replace(
            resource,
            signers=signers,
            occupancies=occupancies,
            timeline=timeline_page.items,
            timeline_next_cursor=timeline_page.next_cursor,
            security_deposit_id=security_deposit_id,
            planned_occupant_customer_ids=planned_occupants,
            planned_occupants=planned_people,
            service_terms=service_terms,
        )

    @staticmethod
    def _actor_id(actor: AuthenticatedActor) -> UUID:
        try:
            return UUID(actor.actor_id)
        except ValueError as exc:
            raise LeaseAuthorizationError("Lease actor is invalid") from exc

    def _service(self, property_id: UUID, actor: AuthenticatedActor) -> PostgresLeaseService:
        return PostgresLeaseService(self._database_url, property_id, self._actor_id(actor))

    def draft(
        self,
        property_id: UUID,
        command: LeaseDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        self._service(property_id, actor).draft_with_terms(command, actor=actor)
        return self.get(command.lease_id)

    def update_draft(
        self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).update_draft(command, actor=actor)
        return self.get(command.lease_id)

    def add_signer(
        self, command: LeaseAddSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).add_signer(command, actor=actor)
        return self.get(command.lease_id)

    def record_signature(
        self, command: LeaseRecordSignatureCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).record_signature(command, actor=actor)
        return self.get(command.lease_id)

    def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).sign(command, actor=actor)
        return self.get(command.lease_id)

    def terminate(
        self, command: LeaseTerminateCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).terminate(command, actor=actor)
        return self.get(command.lease_id)

    def complete_move_in(
        self,
        property_id: UUID,
        command: CompleteMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> MoveInSnapshot:
        lease = self.get(command.lease_id)
        if lease.security_deposit_id is not None:
            try:
                with psycopg.connect(self._database_url) as connection:
                    deposit = connection.execute(
                        "SELECT id FROM app.deposits WHERE reservation_id=%s",
                        (command.reservation_id,),
                    ).fetchone()
            except psycopg.Error as exc:
                raise LeaseResourceUnavailable from exc
            if deposit is None or UUID(str(deposit[0])) != lease.security_deposit_id:
                raise MoveInInvalidError(
                    "Move-in Security Deposit does not match the approved Lease source"
                )
        service = PostgresMoveInService(self._database_url, property_id, self._actor_id(actor))
        return service.complete(command, actor=actor)

    def cancel(self, command: LeaseCancelCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        current = self.get(command.lease_id)
        self._service(current.property_id, actor).cancel(command, actor=actor)
        return self.get(command.lease_id)

    def record_move_in(
        self,
        property_id: UUID,
        command: RecordLeaseMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        service = PostgresMoveInService(self._database_url, property_id, self._actor_id(actor))
        service.record_lease_move_in(command, actor=actor)
        return self.get(command.lease_id)

    def add_occupant(
        self,
        property_id: UUID,
        command: AddLeaseOccupantCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        service = PostgresMoveInService(self._database_url, property_id, self._actor_id(actor))
        service.add_lease_occupant(command, actor=actor)
        return self.get(command.lease_id)

    def move_out_occupant(
        self,
        property_id: UUID,
        command: OccupantMoveOutCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        service = PostgresMoveInService(self._database_url, property_id, self._actor_id(actor))
        service.move_out_lease_occupant(command, actor=actor)
        return self.get(command.lease_id)


class LeaseDraftSignerSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: UUID
    customer_id: UUID


class LeaseServiceTermSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: UUID
    property_service_id: UUID
    applicable_from: date
    applicable_through: date | None = None
    service_approval_period_id: UUID
    terms_reference: Annotated[str, Field(min_length=1, max_length=500)]


class LeasePetTermSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    approved_date: date
    deposit_required_by_signed_terms: bool
    pet_description: Annotated[str | None, Field(max_length=500)] = None


class LeaseDraftSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: UUID
    unit_id: UUID
    primary_tenant_id: UUID
    primary_signer_id: UUID
    start_date: date | None = None
    end_date: date | None = None
    monthly_rent_usd_cents: Annotated[int | None, Field(gt=0)] = None
    predecessor_lease_id: UUID | None = None
    additional_signers: Annotated[list[LeaseDraftSignerSource], Field(max_length=19)]
    planned_occupant_customer_ids: Annotated[list[UUID], Field(max_length=20)]
    service_terms: Annotated[list[LeaseServiceTermSource], Field(max_length=20)]
    pet_term: LeasePetTermSource | None
    security_deposit_id: UUID | None
    event_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseDraftUpdateSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    start_date: date | None = None
    end_date: date | None = None
    monthly_rent_usd_cents: Annotated[int | None, Field(gt=0)] = None
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseSignerSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: UUID
    customer_id: UUID
    event_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]


# Q-2026-10-14-110: no signing time in a request; the database's own time is recorded,
# and a body that still sends one is refused (extra="forbid").
class LeaseSignatureSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseRenewSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: UUID
    primary_signer_id: UUID
    event_id: UUID
    start_date: date
    end_date: date
    monthly_rent_usd_cents: Annotated[int, Field(gt=0)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class TerminationContextSource(BaseModel):
    """Explicit signed-Lease authority; the database verifies every basis rule."""

    model_config = ConfigDict(extra="forbid")

    basis: TerminationBasis
    signed_lease_provision: Annotated[str, Field(min_length=1, max_length=2000)]
    approved_grounds: Annotated[str, Field(min_length=1, max_length=2000)]
    management_authorization_reference: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=500)]
    notice_required: bool
    notice_id: UUID | None = None
    notice_period_ends_on: date | None = None
    notice_exception_reason: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    warning_ids: Annotated[list[UUID], Field(max_length=100)] = Field(default_factory=list)

    def to_context(self) -> TerminationContext:
        return TerminationContext(
            basis=self.basis,
            signed_lease_provision=self.signed_lease_provision,
            approved_grounds=self.approved_grounds,
            management_authorization_reference=self.management_authorization_reference,
            evidence_reference=self.evidence_reference,
            notice_required=self.notice_required,
            notice_id=self.notice_id,
            notice_period_ends_on=self.notice_period_ends_on,
            notice_exception_reason=self.notice_exception_reason,
            warning_ids=tuple(self.warning_ids),
        )


class LeaseTerminateSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    actual_termination_date: date
    governing_event_reference: Annotated[str, Field(min_length=1, max_length=255)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    context: TerminationContextSource | None = None


class MoveInOccupantSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occupancy_id: UUID
    customer_id: UUID


class MoveInCommandSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    expected_lease_version: Annotated[int, Field(gt=0)]
    expected_unit_version: Annotated[int, Field(gt=0)]
    actual_move_in_date: date
    occupants: Annotated[list[MoveInOccupantSource], Field(min_length=1, max_length=20)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseCancelSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseMoveInSource(BaseModel):
    """Move-in of a Lease whose signing already completed its Reservation (DL-066)."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    actual_move_in_date: date
    occupants: Annotated[list[MoveInOccupantSource], Field(min_length=1, max_length=20)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class LeaseOccupantSource(BaseModel):
    """V1-060 B6 (DL-102): Add occupant. Before the move-in, no Occupancy and no date."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    customer_id: UUID
    occupancy_id: UUID | None = None
    move_in_date: date | None = None
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class OccupantMoveOutSource(BaseModel):
    """V1-061 (DL-111): Move out one occupant; a Joint Signer names the Signers who agreed."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    move_out_date: date
    agreed_signer_customer_ids: Annotated[list[UUID], Field(max_length=100)] = []
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class MoveInSource(MoveInCommandSource):
    lease_id: UUID


class OccupancyCreateSource(MoveInCommandSource):
    reservation_id: UUID


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


def _reject_unknown_query(request: Request, allowed: frozenset[str]) -> None:
    unknown = sorted(set(request.query_params) - allowed)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported query parameter.",
        )


def _body(resource: LeaseResource, actor: AuthenticatedActor) -> dict[str, object]:
    result = asdict(resource)
    result.update(
        {
            "lease_id": str(resource.lease_id),
            "property_id": str(resource.property_id),
            "unit_id": str(resource.unit_id),
            "primary_tenant_id": str(resource.primary_tenant_id),
            "predecessor_lease_id": (
                None
                if resource.predecessor_lease_id is None
                else str(resource.predecessor_lease_id)
            ),
            "can_edit": resource.status is LeaseStatus.DRAFTED
            and _can(actor, resource.property_id, LEASE_DRAFT_CAPABILITY),
            "can_manage_signers": resource.status is LeaseStatus.DRAFTED
            and _can(actor, resource.property_id, LEASE_SIGNER_MANAGE_CAPABILITY),
            "can_sign": resource.status is LeaseStatus.DRAFTED
            and _can(actor, resource.property_id, LEASE_SIGN_CAPABILITY),
            "can_terminate": resource.status is LeaseStatus.SIGNED
            and _can(actor, resource.property_id, LEASE_TERMINATE_CAPABILITY),
            "can_move_in": resource.status is LeaseStatus.SIGNED
            and _can(actor, resource.property_id, MOVE_IN_CAPABILITY),
            "can_renew": resource.status in (LeaseStatus.SIGNED, LeaseStatus.TERMINATED)
            and _can(actor, resource.property_id, LEASE_DRAFT_CAPABILITY),
        }
    )
    return result


def _check_rent(
    flow: LeaseResourceFlow,
    actor: AuthenticatedActor,
    property_id: UUID,
    unit_id: UUID,
    rent: int | None,
    security_deposit_id: UUID | None,
) -> None:
    """V1-061 (owner 2026-10-29, DL-110): a Rent below the Unit's default Rent needs a Manager or
    the Owner; the reason of the command says why."""
    if rent is None or _can(actor, property_id, RENT_BELOW_DEFAULT_CAPABILITY):
        return
    floor = flow.rent_floor(unit_id, security_deposit_id)
    if floor is not None and rent < floor:
        raise RefusedRequest(RENT_BELOW_UNIT_DEFAULT)


def _translate(exc: Exception) -> HTTPException | RefusedRequest:
    if isinstance(exc, (HTTPException, RefusedRequest)):
        return exc
    if isinstance(exc, LeaseEndDateNotMonthEndError):
        return RefusedRequest(LEASE_END_DATE_NOT_MONTH_END)
    if isinstance(exc, LeaseRequiredServiceMissingError):
        return RefusedRequest(LEASE_REQUIRED_SERVICE_MISSING)
    if isinstance(exc, OccupantMoveOutRefusedError):
        return RefusedRequest(OCCUPANT_MOVE_OUT_REFUSALS[exc.reason])
    if isinstance(exc, (LeaseResourceNotFound, LeaseNotFoundError, MoveInNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, (LeaseVersionConflictError, MoveInVersionConflictError)):
        return HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    if isinstance(exc, (LeaseCommandConflictError, MoveInConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT)
    if isinstance(
        exc,
        (LeaseCommandInvalidError, MoveInInvalidError, LeaseResourceInvalid, ValueError),
    ):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if isinstance(exc, (LeaseAuthorizationError, MoveInAuthorizationError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def create_lease_router(
    resolver: ActorResolver,
    flow: LeaseResourceFlow,
    settings: Settings,
) -> APIRouter:
    """Create API-035 through API-038 and the coordinated move-in route."""
    router = APIRouter(prefix="/api/v1", tags=["leases"])

    @router.get("/properties/{property_id}/leases")
    def list_leases(
        property_id: UUID,
        request: Request,
        response: Response,
        lease_status: Annotated[LeaseStatus | None, Query(alias="status")] = None,
        unit_id: Annotated[UUID | None, Query()] = None,
        customer_id: Annotated[UUID | None, Query()] = None,
        starts_on_or_after: Annotated[date | None, Query()] = None,
        ends_on_or_before: Annotated[date | None, Query()] = None,
        period: Annotated[LeasePeriodFilter | None, Query()] = None,
        as_of: Annotated[date | None, Query()] = None,
        approaching_days: Annotated[int, Query(ge=1, le=365)] = 30,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        _reject_unknown_query(
            request,
            frozenset(
                {
                    "status",
                    "unit_id",
                    "customer_id",
                    "starts_on_or_after",
                    "ends_on_or_before",
                    "period",
                    "as_of",
                    "approaching_days",
                    "limit",
                    "cursor",
                }
            ),
        )
        actor = _require_actor(request, resolver)
        _require(actor, property_id, LEASE_READ_CAPABILITY)
        try:
            page = flow.list(
                property_id,
                lease_status=lease_status,
                unit_id=unit_id,
                customer_id=customer_id,
                starts_on_or_after=starts_on_or_after,
                ends_on_or_before=ends_on_or_before,
                period=period,
                as_of=as_of,
                approaching_days=approaching_days,
                limit=limit,
                cursor=cursor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "data": [_body(item, actor) for item in page.items],
            "page": {"next_cursor": page.next_cursor, "limit": limit},
            "meta": {
                "request_id": request.state.request_id,
                "can_create": _can(actor, property_id, LEASE_DRAFT_CAPABILITY),
            },
        }

    @router.post("/properties/{property_id}/leases", status_code=status.HTTP_201_CREATED)
    def create_lease(
        property_id: UUID,
        source: LeaseDraftSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require(actor, property_id, LEASE_DRAFT_CAPABILITY)
        require_browser_mutation(request, settings)
        try:
            _check_rent(
                flow,
                actor,
                property_id,
                source.unit_id,
                source.monthly_rent_usd_cents,
                source.security_deposit_id,
            )
            resource = flow.draft(
                property_id,
                LeaseDraftCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=source.lease_id,
                    unit_id=source.unit_id,
                    primary_tenant_id=source.primary_tenant_id,
                    primary_signer_id=source.primary_signer_id,
                    start_date=source.start_date,
                    end_date=source.end_date,
                    monthly_rent_usd_cents=source.monthly_rent_usd_cents,
                    predecessor_lease_id=source.predecessor_lease_id,
                    reason=source.reason,
                    authorization_reference=LEASE_DRAFT_CAPABILITY,
                    additional_signers=tuple(
                        LeaseDraftSigner(value.signer_id, value.customer_id)
                        for value in source.additional_signers
                    ),
                    planned_occupant_customer_ids=tuple(source.planned_occupant_customer_ids),
                    service_terms=tuple(
                        LeaseServiceTerm(
                            term_id=value.term_id,
                            property_service_id=value.property_service_id,
                            applicable_from=value.applicable_from,
                            applicable_through=value.applicable_through,
                            service_approval_period_id=value.service_approval_period_id,
                            terms_reference=value.terms_reference,
                        )
                        for value in source.service_terms
                    ),
                    pet_term=(
                        None
                        if source.pet_term is None
                        else LeasePetTerm(
                            approval_id=source.pet_term.approval_id,
                            approved_date=source.pet_term.approved_date,
                            deposit_required_by_signed_terms=(
                                source.pet_term.deposit_required_by_signed_terms
                            ),
                            pet_description=source.pet_term.pet_description,
                        )
                    ),
                    security_deposit_id=source.security_deposit_id,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/api/v1/leases/{resource.lease_id}"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.get("/leases/{lease_id}")
    def get_lease(lease_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(lease_id, visibility=timeline_visibility(actor))
            _require(actor, resource.property_id, LEASE_READ_CAPABILITY)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.patch("/leases/{lease_id}")
    def update_lease(
        lease_id: UUID,
        source: LeaseDraftUpdateSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_DRAFT_CAPABILITY)
            require_browser_mutation(request, settings)
            if (
                "monthly_rent_usd_cents" in source.model_fields_set
                and source.monthly_rent_usd_cents != current.monthly_rent_usd_cents
            ):
                _check_rent(
                    flow,
                    actor,
                    current.property_id,
                    current.unit_id,
                    source.monthly_rent_usd_cents,
                    current.security_deposit_id,
                )
            resource = flow.update_draft(
                LeaseUpdateDraftCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_version=_version(if_match),
                    start_date=(
                        source.start_date
                        if "start_date" in source.model_fields_set
                        else current.start_date
                    ),
                    end_date=(
                        source.end_date
                        if "end_date" in source.model_fields_set
                        else current.end_date
                    ),
                    monthly_rent_usd_cents=(
                        source.monthly_rent_usd_cents
                        if "monthly_rent_usd_cents" in source.model_fields_set
                        else current.monthly_rent_usd_cents
                    ),
                    reason=source.reason,
                    authorization_reference=LEASE_DRAFT_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.get("/leases/{lease_id}/signers")
    def list_signers(lease_id: UUID, request: Request) -> dict[str, object]:
        _reject_unknown_query(request, frozenset())
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(lease_id)
            _require(actor, resource.property_id, LEASE_READ_CAPABILITY)
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": [asdict(item) for item in resource.signers],
            "page": {"next_cursor": None, "limit": 20},
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/signers", status_code=status.HTTP_201_CREATED)
    def add_signer(
        lease_id: UUID,
        source: LeaseSignerSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_SIGNER_MANAGE_CAPABILITY)
            require_browser_mutation(request, settings)
            if len(current.signers) >= 20:
                raise LeaseResourceInvalid("a Lease may have at most twenty Signers")
            resource = flow.add_signer(
                LeaseAddSignerCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    signer_id=source.signer_id,
                    customer_id=source.customer_id,
                    expected_version=_version(if_match),
                    reason=source.reason,
                    authorization_reference=LEASE_SIGNER_MANAGE_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/api/v1/lease-signers/{source.signer_id}"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.patch("/lease-signers/{signer_id}")
    def record_signature(
        signer_id: UUID,
        source: LeaseSignatureSource,
        request: Request,
        response: Response,
        lease_id: Annotated[UUID, Query()],
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_SIGN_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.record_signature(
                LeaseRecordSignatureCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    signer_id=signer_id,
                    expected_version=_version(if_match),
                    signed_at=None,
                    reason=source.reason,
                    authorization_reference=LEASE_SIGN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.get("/leases/{lease_id}/occupancies")
    def list_occupancies(lease_id: UUID, request: Request) -> dict[str, object]:
        _reject_unknown_query(request, frozenset())
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(lease_id)
            _require(actor, resource.property_id, LEASE_READ_CAPABILITY)
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": [asdict(item) for item in resource.occupancies],
            "page": {"next_cursor": None, "limit": 20},
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/leases/{lease_id}/timeline")
    def list_timeline(
        lease_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        _reject_unknown_query(request, frozenset({"limit", "cursor"}))
        actor = _require_actor(request, resolver)
        try:
            resource = flow.get(lease_id)
            _require(actor, resource.property_id, LEASE_READ_CAPABILITY)
            page = flow.timeline(
                lease_id, limit=limit, cursor=cursor, visibility=timeline_visibility(actor)
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": [asdict(item) for item in page.items],
            "page": {"next_cursor": page.next_cursor, "limit": limit},
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/occupancies", status_code=status.HTTP_201_CREATED)
    def create_coordinated_occupancy(
        lease_id: UUID,
        source: OccupancyCreateSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            lease = flow.get(lease_id)
            _require(actor, lease.property_id, MOVE_IN_CAPABILITY)
            require_browser_mutation(request, settings)
            snapshot = flow.complete_move_in(
                lease.property_id,
                CompleteMoveInCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    reservation_id=source.reservation_id,
                    lease_id=lease_id,
                    expected_reservation_version=_version(if_match),
                    expected_lease_version=source.expected_lease_version,
                    expected_unit_version=source.expected_unit_version,
                    actual_move_in_date=source.actual_move_in_date,
                    occupants=tuple(
                        MoveInOccupant(value.occupancy_id, value.customer_id)
                        for value in source.occupants
                    ),
                    reason=source.reason,
                    authorization_reference=MOVE_IN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Location"] = f"/api/v1/leases/{lease_id}/occupancies"
        return {"data": asdict(snapshot), "meta": {"request_id": request.state.request_id}}

    @router.post("/occupancies/{occupancy_id}/end")
    def reject_move_out_boundary(occupancy_id: UUID, request: Request) -> None:
        del occupancy_id
        _require_actor(request, resolver)
        require_browser_mutation(request, settings)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    @router.post("/leases/{lease_id}/occupancies/{occupancy_id}/move-out")
    def move_out_lease_occupant(
        lease_id: UUID,
        occupancy_id: UUID,
        source: OccupantMoveOutSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """V1-061 (owner 2026-10-29, DL-111): one person moves out on their own day; never the
        Primary Tenant, a Joint Signer only with every other Signer agreeing, and never the last
        Signer living there."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, MOVE_IN_CAPABILITY)
            require_browser_mutation(request, settings)
            if len(set(source.agreed_signer_customer_ids)) != len(
                source.agreed_signer_customer_ids
            ):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
            resource = flow.move_out_occupant(
                current.property_id,
                OccupantMoveOutCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_lease_version=_version(if_match),
                    occupancy_id=occupancy_id,
                    move_out_date=source.move_out_date,
                    agreed_signer_customer_ids=tuple(source.agreed_signer_customer_ids),
                    reason=source.reason,
                    authorization_reference=MOVE_IN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    # V1-061: the plain `POST /leases/{lease_id}/sign` signed a Lease with no money and is
    # removed; Sign Lease with payment (DL-108, lease_signing_api) is the only way to sign.

    @router.post("/leases/{lease_id}/renew", status_code=status.HTTP_201_CREATED)
    def renew_lease(
        lease_id: UUID,
        source: LeaseRenewSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_DRAFT_CAPABILITY)
            require_browser_mutation(request, settings)
            _check_rent(
                flow,
                actor,
                current.property_id,
                current.unit_id,
                source.monthly_rent_usd_cents,
                None,
            )
            resource = flow.draft(
                current.property_id,
                LeaseDraftCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=source.lease_id,
                    unit_id=current.unit_id,
                    primary_tenant_id=current.primary_tenant_id,
                    primary_signer_id=source.primary_signer_id,
                    start_date=source.start_date,
                    end_date=source.end_date,
                    monthly_rent_usd_cents=source.monthly_rent_usd_cents,
                    predecessor_lease_id=lease_id,
                    reason=source.reason,
                    authorization_reference=LEASE_DRAFT_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        response.headers["Location"] = f"/api/v1/leases/{resource.lease_id}"
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/leases/{lease_id}/cancel")
    def cancel_lease(
        lease_id: UUID,
        source: LeaseCancelSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """V1-058: cancel a draft Lease (BR-LEASE-004); a signed Lease is never cancelled."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_DRAFT_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.cancel(
                LeaseCancelCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_version=_version(if_match),
                    reason=source.reason,
                    authorization_reference=LEASE_DRAFT_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/leases/{lease_id}/move-in")
    def record_lease_move_in(
        lease_id: UUID,
        source: LeaseMoveInSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """V1-058: the physical move-in of a signed Lease starts its Occupancies (DL-066)."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, MOVE_IN_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.record_move_in(
                current.property_id,
                RecordLeaseMoveInCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_lease_version=_version(if_match),
                    actual_move_in_date=source.actual_move_in_date,
                    occupants=tuple(
                        MoveInOccupant(value.occupancy_id, value.customer_id)
                        for value in source.occupants
                    ),
                    reason=source.reason,
                    authorization_reference=MOVE_IN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/leases/{lease_id}/occupants")
    def add_lease_occupant(
        lease_id: UUID,
        source: LeaseOccupantSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """V1-060 B6 (DL-102): Add occupant on a draft or a running Lease (BR-OCC-004)."""
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, MOVE_IN_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.add_occupant(
                current.property_id,
                AddLeaseOccupantCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_lease_version=_version(if_match),
                    customer_id=source.customer_id,
                    occupancy_id=source.occupancy_id,
                    move_in_date=source.move_in_date,
                    reason=source.reason,
                    authorization_reference=MOVE_IN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/leases/{lease_id}/terminate")
    def terminate_lease(
        lease_id: UUID,
        source: LeaseTerminateSource,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get(lease_id)
            _require(actor, current.property_id, LEASE_TERMINATE_CAPABILITY)
            require_browser_mutation(request, settings)
            resource = flow.terminate(
                LeaseTerminateCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    lease_id=lease_id,
                    expected_version=_version(if_match),
                    actual_termination_date=source.actual_termination_date,
                    # The database's own time at the command (Q-2026-10-14-112).
                    occurred_at=None,
                    governing_event_reference=source.governing_event_reference,
                    reason=source.reason,
                    authorization_reference=LEASE_TERMINATE_CAPABILITY,
                    context=source.context.to_context() if source.context is not None else None,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["ETag"] = f'"{resource.version}"'
        return {"data": _body(resource, actor), "meta": {"request_id": request.state.request_id}}

    @router.post("/reservations/{reservation_id}/complete-move-in")
    def complete_move_in(
        reservation_id: UUID,
        source: MoveInSource,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        try:
            lease = flow.get(source.lease_id)
            _require(actor, lease.property_id, MOVE_IN_CAPABILITY)
            require_browser_mutation(request, settings)
            snapshot = flow.complete_move_in(
                lease.property_id,
                CompleteMoveInCommand(
                    idempotency_key=idempotency_key,
                    event_id=source.event_id,
                    reservation_id=reservation_id,
                    lease_id=source.lease_id,
                    expected_reservation_version=_version(if_match),
                    expected_lease_version=source.expected_lease_version,
                    expected_unit_version=source.expected_unit_version,
                    actual_move_in_date=source.actual_move_in_date,
                    occupants=tuple(
                        MoveInOccupant(value.occupancy_id, value.customer_id)
                        for value in source.occupants
                    ),
                    reason=source.reason,
                    authorization_reference=MOVE_IN_CAPABILITY,
                ),
                actor=actor,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return {"data": asdict(snapshot), "meta": {"request_id": request.state.request_id}}

    return router
