"""Authorized HTTP queries for immutable audit events.

The queries change no record. A new audit search (its first page) writes one `audit.searched`
event of its own (DL-072 answer 14); the next pages of the same search do not.
"""

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from property_rental.audit import (
    AuditConnection,
    AuditEvent,
    AuditSource,
    AuditValue,
    _is_forbidden_audit_key,
    _reject_secret_text,
    _validate_classified_audit_number,
    _validate_classified_audit_text,
    is_file_fingerprint,
    public_audit_filters,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.reports import report_actor

AUDIT_VIEW_CAPABILITY: Final = "audit.view"
DEFAULT_AUDIT_PAGE_SIZE: Final = 50
MAX_AUDIT_PAGE_SIZE: Final = 100


class AuditQueryUnavailable(Exception):
    """Raised when audit query persistence is unavailable."""


class AuditQueryForbidden(Exception):
    """Raised when an actor may not view the requested property's audit data."""


class AuditQueryNotFound(Exception):
    """Raised when a requested audited resource cannot be resolved."""


class AuditQueryInvalid(Exception):
    """Raised when bounded audit query rules reject the requested filters."""


@dataclass(frozen=True, slots=True)
class AuditPageRequest:
    """Bounded cursor pagination requested by an audit client."""

    limit: int = DEFAULT_AUDIT_PAGE_SIZE
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyAuditQuery:
    """Bounded filters for a property-scoped global audit search."""

    property_id: UUID
    page: AuditPageRequest
    from_date: date | None = None
    to_date: date | None = None
    actor_id: UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    customer_id: UUID | None = None
    unit_id: UUID | None = None
    lease_id: UUID | None = None
    correlation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ResourceAuditQuery:
    """Cursor request for one resource's immutable event timeline."""

    resource_type: str
    resource_id: UUID
    page: AuditPageRequest


@dataclass(frozen=True, slots=True)
class AuditEventPage:
    """One stable page returned by an audit query repository."""

    events: Sequence[AuditEvent]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAuditResource:
    """Authorized Property scopes and canonical singular audit entity type."""

    property_ids: frozenset[UUID]
    entity_type: str


class AuditEventQueryRepository(Protocol):
    """Read-only persistence boundary for property-filtered audit events."""

    def search_property(self, query: PropertyAuditQuery) -> AuditEventPage:
        """Return events constrained to the query's property and bounded filters."""
        ...

    def resource_timeline(
        self,
        *,
        property_ids: frozenset[UUID],
        entity_type: str,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        """Return a resource timeline constrained to its authorized property."""
        ...


class AuditResourceScopeResolver(Protocol):
    """Authoritative resource lookup constrained to already-authorized Properties."""

    def resolve_authorized_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        authorized_property_ids: frozenset[UUID],
    ) -> ResolvedAuditResource | None:
        """Return ownership only when the resource exists inside an allowed Property."""
        ...


class UnavailableAuditResourceScopeResolver:
    """Fail closed until an authoritative resource repository is supplied."""

    def resolve_authorized_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        authorized_property_ids: frozenset[UUID],
    ) -> ResolvedAuditResource | None:
        del resource_type, resource_id, authorized_property_ids
        raise AuditQueryUnavailable


class PostgresAuditResourceScopeResolver:
    """Resolve supported resource families from their authoritative relational rows."""

    _audited_entity_types: Final[dict[str, str]] = {
        "adjustments": "adjustment",
        "allocations": "payment_allocation",
        "customer-credits": "customer_credit",
        "deposits": "deposit",
        "exchange-rate-records": "exchange_rate_record",
        "final-settlements": "final_settlement",
        "invoices": "invoice",
        "late-payment-charges": "late_payment_charge",
        "late-payment-decisions": "late_payment_decision",
        "meters": "utility_meter",
        "payments": "payment",
        "rates": "rate",
        "refunds": "refund",
        "reservations": "reservation",
        "utility-consumption-periods": "utility_consumption_period",
        "utility-readings": "utility_reading",
    }

    _queries: Final[dict[str, tuple[str, str]]] = {
        "properties": (
            "property",
            "SELECT id FROM app.properties WHERE id = %s AND id = ANY(%s::uuid[])",
        ),
        "units": (
            "unit",
            "SELECT property_id FROM app.units WHERE id = %s AND property_id = ANY(%s::uuid[])",
        ),
        "leases": (
            "lease",
            "SELECT unit.property_id FROM app.leases AS lease "
            "JOIN app.units AS unit ON unit.id = lease.unit_id "
            "WHERE lease.id = %s AND unit.property_id = ANY(%s::uuid[])",
        ),
        "occupancies": (
            "occupancy",
            "SELECT unit.property_id FROM app.occupancies AS occupancy "
            "JOIN app.leases AS lease ON lease.id = occupancy.lease_id "
            "JOIN app.units AS unit ON unit.id = lease.unit_id "
            "WHERE occupancy.id = %s AND unit.property_id = ANY(%s::uuid[])",
        ),
        "reservations": (
            "reservation",
            "SELECT unit.property_id FROM app.reservations AS reservation "
            "JOIN app.units AS unit ON unit.id = reservation.unit_id "
            "WHERE reservation.id = %s AND unit.property_id = ANY(%s::uuid[])",
        ),
        "customers": (
            "customer",
            "SELECT DISTINCT related.property_id FROM ("
            "SELECT unit.property_id FROM app.reservations AS reservation "
            "JOIN app.units AS unit ON unit.id = reservation.unit_id "
            "WHERE reservation.customer_id = %s "
            "UNION ALL "
            "SELECT unit.property_id FROM app.leases AS lease "
            "JOIN app.units AS unit ON unit.id = lease.unit_id "
            "WHERE lease.primary_tenant_id = %s "
            "UNION ALL "
            "SELECT unit.property_id FROM app.lease_signers AS signer "
            "JOIN app.leases AS lease ON lease.id = signer.lease_id "
            "JOIN app.units AS unit ON unit.id = lease.unit_id "
            "WHERE signer.customer_id = %s "
            "UNION ALL "
            "SELECT unit.property_id FROM app.occupancies AS occupancy "
            "JOIN app.leases AS lease ON lease.id = occupancy.lease_id "
            "JOIN app.units AS unit ON unit.id = lease.unit_id "
            "WHERE occupancy.customer_id = %s "
            ") AS related WHERE related.property_id = ANY(%s::uuid[])",
        ),
    }

    def __init__(self, connection: AuditConnection) -> None:
        self._connection = connection

    def resolve_authorized_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        authorized_property_ids: frozenset[UUID],
    ) -> ResolvedAuditResource | None:
        definition = self._queries.get(resource_type)
        if definition is None:
            if resource_type in self._audited_entity_types:
                raise AuditQueryUnavailable
            raise AuditQueryInvalid
        entity_type, query = definition
        resource_parameters: tuple[object, ...]
        if resource_type == "customers":
            resource_parameters = (
                resource_id,
                resource_id,
                resource_id,
                resource_id,
                list(sorted(authorized_property_ids, key=str)),
            )
        else:
            resource_parameters = (
                resource_id,
                list(sorted(authorized_property_ids, key=str)),
            )
        rows = self._connection.execute(query, resource_parameters).fetchall()
        if not rows:
            return None
        return ResolvedAuditResource(
            property_ids=frozenset(UUID(str(row[0])) for row in rows),
            entity_type=entity_type,
        )


class AuditEventQueryFlow(Protocol):
    """Application boundary for authorized audit-event queries."""

    def search_property(
        self,
        actor: AuthenticatedActor,
        query: PropertyAuditQuery,
    ) -> AuditEventPage:
        """Return an authorized property-wide audit page."""
        ...

    def resource_timeline(
        self,
        actor: AuthenticatedActor,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        """Return an authorized resource audit page."""
        ...


class PostgresAuditEventQueryRepository:
    """Concrete keyset-paginated queries over append-only audit storage."""

    _columns = """id, actor_id, action, entity_type, entity_id, occurred_at,
        business_date, reason, authorization_reference, previous_state,
        resulting_state, correlation_id, source, property_id, outcome,
        authorization_evidence, linked_source_event_id, customer_id, unit_id,
        lease_id"""

    def __init__(self, connection: AuditConnection) -> None:
        self._connection = connection

    def search_property(self, query: PropertyAuditQuery) -> AuditEventPage:
        clauses = ["property_id = %s"]
        parameters: list[object] = [query.property_id]
        for expression, value in (
            ("business_date >= %s", query.from_date),
            ("business_date <= %s", query.to_date),
            ("actor_id = %s", query.actor_id),
            ("action = %s", query.action),
            ("entity_type = %s", query.resource_type),
            ("entity_id = %s", query.resource_id),
            ("correlation_id = %s", query.correlation_id),
        ):
            if value is not None:
                clauses.append(expression)
                parameters.append(value)
        for column, entity_type, value in (
            ("customer_id", "customer", query.customer_id),
            ("unit_id", "unit", query.unit_id),
            ("lease_id", "lease", query.lease_id),
        ):
            if value is not None:
                clauses.append(f"({column} = %s OR (entity_type = %s AND entity_id = %s))")
                parameters.extend((value, entity_type, value))
        self._apply_cursor(clauses, parameters, query.page.cursor)
        parameters.append(query.page.limit + 1)
        rows = self._connection.execute(
            f"SELECT {self._columns} FROM app.audit_events "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC, id DESC LIMIT %s",
            tuple(parameters),
        ).fetchall()
        return self._page(rows, query.page.limit)

    def resource_timeline(
        self,
        *,
        property_ids: frozenset[UUID],
        entity_type: str,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        relation_column = {
            "customer": "customer_id",
            "unit": "unit_id",
            "lease": "lease_id",
        }.get(entity_type)
        resource_clause = "(entity_type = %s AND entity_id = %s)"
        parameters: list[object] = [
            list(sorted(property_ids, key=str)),
            entity_type,
            query.resource_id,
        ]
        if relation_column is not None:
            resource_clause = f"({resource_clause} OR {relation_column} = %s)"
            parameters.append(query.resource_id)
        clauses = ["property_id = ANY(%s::uuid[])", resource_clause]
        self._apply_cursor(clauses, parameters, query.page.cursor)
        parameters.append(query.page.limit + 1)
        rows = self._connection.execute(
            f"SELECT {self._columns} FROM app.audit_events "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC, id DESC LIMIT %s",
            tuple(parameters),
        ).fetchall()
        return self._page(rows, query.page.limit)

    @staticmethod
    def _apply_cursor(clauses: list[str], parameters: list[object], cursor: str | None) -> None:
        if cursor is None:
            return
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            instant_text, event_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
            instant = datetime.fromisoformat(instant_text)
            if instant.utcoffset() is None:
                raise ValueError("cursor timestamp must be timezone-aware")
            identifier = UUID(event_id)
        except (ValueError, UnicodeError) as error:
            raise AuditQueryInvalid from error
        clauses.append("(occurred_at, id) < (%s, %s)")
        parameters.extend((instant.astimezone(UTC), identifier))

    @classmethod
    def _page(cls, rows: list[tuple[object, ...]], limit: int) -> AuditEventPage:
        events = tuple(cls._event(row) for row in rows[:limit])
        cursor = None
        if len(rows) > limit and events:
            last = events[-1]
            raw = f"{last.occurred_at.isoformat()}|{last.event_id}".encode()
            cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return AuditEventPage(events=events, next_cursor=cursor)

    @staticmethod
    def _event(row: tuple[object, ...]) -> AuditEvent:
        source = _safe_loaded_text(row[12], "source")
        if source not in {"UI", "API", "SCHEDULED", "ADMINISTRATIVE"}:
            raise ValueError("stored audit source is not canonical")
        return AuditEvent(
            event_id=UUID(str(row[0])),
            actor_id=UUID(str(row[1])),
            action=_safe_loaded_text(row[2], "action"),
            target_type=_safe_loaded_text(row[3], "entity_type"),
            target_id=UUID(str(row[4])),
            occurred_at=row[5]
            if isinstance(row[5], datetime)
            else datetime.fromisoformat(str(row[5])),
            business_date=row[6] if isinstance(row[6], date) else date.fromisoformat(str(row[6])),
            reason=_safe_loaded_text(row[7], "reason"),
            authorization_reference=(
                None if row[8] is None else _safe_loaded_text(row[8], "authorization_reference")
            ),
            previous_state=_freeze_event_state(row[9], str(row[3])),
            resulting_state=_freeze_event_state(row[10], str(row[3])),
            correlation_id=UUID(str(row[11])),
            source=cast(AuditSource, source),
            property_id=UUID(str(row[13])),
            outcome=_safe_loaded_text(row[14], "outcome"),
            authorization_evidence=_freeze_loaded(row[15]),
            linked_source_event_id=(None if row[16] is None else UUID(str(row[16]))),
            customer_id=None if row[17] is None else UUID(str(row[17])),
            unit_id=None if row[18] is None else UUID(str(row[18])),
            lease_id=None if row[19] is None else UUID(str(row[19])),
        )


class PostgresAuditEventQueryFlow:
    """Production flow opening one bounded read transaction per request."""

    def __init__(
        self,
        database_url: str,
        resource_scope_resolver: AuditResourceScopeResolver | None = None,
    ) -> None:
        self._database_url = database_url
        self._resource_scope_resolver = resource_scope_resolver

    def search_property(
        self, actor: AuthenticatedActor, query: PropertyAuditQuery
    ) -> AuditEventPage:
        try:
            with psycopg.connect(self._database_url) as connection:
                page = AuthorizedAuditEventQueryService(
                    PostgresAuditEventQueryRepository(connection),
                    self._resource_scope_resolver,
                ).search_property(actor, query)
                if query.page.cursor is None:
                    record_audit_search(connection, actor, query, len(page.events))
                return page
        except psycopg.Error as error:
            raise AuditQueryUnavailable from error

    def resource_timeline(
        self, actor: AuthenticatedActor, query: ResourceAuditQuery
    ) -> AuditEventPage:
        try:
            with psycopg.connect(self._database_url) as connection:
                resolver = self._resource_scope_resolver or PostgresAuditResourceScopeResolver(
                    connection
                )
                return AuthorizedAuditEventQueryService(
                    PostgresAuditEventQueryRepository(connection),
                    resolver,
                ).resource_timeline(actor, query)
        except psycopg.Error as error:
            raise AuditQueryUnavailable from error


def audit_search_details(query: PropertyAuditQuery, first_page_count: int) -> dict[str, object]:
    """The filters of a new audit search, as its own audit event records them."""
    filters = {
        "from_date": query.from_date,
        "to_date": query.to_date,
        "actor_id": query.actor_id,
        "action": query.action,
        "resource_type": query.resource_type,
        "resource_id": query.resource_id,
        "customer_id": query.customer_id,
        "unit_id": query.unit_id,
        "lease_id": query.lease_id,
        "correlation_id": query.correlation_id,
    }
    return {
        "filters": public_audit_filters(
            {key: str(value) for key, value in filters.items() if value is not None}
        ),
        "first_page_count": first_page_count,
    }


def record_audit_search(
    connection: psycopg.Connection[tuple[object, ...]],
    actor: AuthenticatedActor,
    query: PropertyAuditQuery,
    first_page_count: int,
) -> None:
    """Write the `audit.searched` event in the search's own transaction (DL-072 answer 14)."""
    connection.execute(
        "SELECT app.record_report_activity(%s,%s,%s::uuid[],'audit_search','audit.view',"
        "%s::jsonb,%s)",
        (
            UUID(actor.actor_id),
            query.property_id,
            list(report_actor(actor).property_ids),
            json.dumps(audit_search_details(query, first_page_count)),
            uuid4(),
        ),
    )


class AuthorizedAuditEventQueryService:
    """Enforce dedicated capability and property scope before returning audit data."""

    def __init__(
        self,
        repository: AuditEventQueryRepository,
        resource_scope_resolver: AuditResourceScopeResolver | None = None,
    ) -> None:
        self._repository = repository
        self._resource_scope_resolver = resource_scope_resolver

    def search_property(
        self,
        actor: AuthenticatedActor,
        query: PropertyAuditQuery,
    ) -> AuditEventPage:
        self._authorize(actor, query.property_id)
        if (
            query.from_date is not None
            and query.to_date is not None
            and query.from_date > query.to_date
        ):
            raise AuditQueryInvalid
        return self._repository.search_property(query)

    def resource_timeline(
        self,
        actor: AuthenticatedActor,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        authorized_property_ids = self._authorized_property_ids(actor)
        if not authorized_property_ids:
            raise AuditQueryForbidden
        resolver = self._resource_scope_resolver or UnavailableAuditResourceScopeResolver()
        resource = resolver.resolve_authorized_resource(
            query.resource_type,
            query.resource_id,
            authorized_property_ids,
        )
        if resource is None:
            raise AuditQueryNotFound
        return self._repository.resource_timeline(
            property_ids=resource.property_ids,
            entity_type=resource.entity_type,
            query=query,
        )

    @staticmethod
    def _authorized_property_ids(actor: AuthenticatedActor) -> frozenset[UUID]:
        identifiers: set[UUID] = set()
        for grant in actor.capability_grants:
            if grant.capability != AUDIT_VIEW_CAPABILITY:
                continue
            for property_id in grant.property_ids:
                try:
                    identifiers.add(UUID(property_id))
                except ValueError:
                    continue
        return frozenset(identifiers)

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID) -> None:
        requirement = AuthorizationRequirement(
            capability=AUDIT_VIEW_CAPABILITY,
            property_id=str(property_id),
        )
        if not is_authorized(actor, requirement):
            raise AuditQueryForbidden


class UnavailableAuditEventQueryFlow:
    """Safe application default when audit query persistence is not configured."""

    def search_property(
        self,
        actor: AuthenticatedActor,
        query: PropertyAuditQuery,
    ) -> AuditEventPage:
        del actor, query
        raise AuditQueryUnavailable

    def resource_timeline(
        self,
        actor: AuthenticatedActor,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        del actor, query
        raise AuditQueryUnavailable


class AuditEventView(BaseModel):
    """Public immutable audit event representation without mutation metadata."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    actor_id: UUID
    property_id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    occurred_at: datetime
    business_date: date
    reason: str
    previous_state: object
    resulting_state: object
    correlation_id: UUID
    outcome: str
    source: str
    linked_source_event_id: UUID | None


class AuditPageMeta(BaseModel):
    """Correlation and cursor metadata for an audit page."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    next_cursor: str | None


class AuditEventPageResponse(BaseModel):
    """Canonical audit-event collection envelope."""

    model_config = ConfigDict(frozen=True)

    data: list[AuditEventView]
    meta: AuditPageMeta


def create_audit_router(
    actor_resolver: ActorResolver,
    query_flow: AuditEventQueryFlow,
) -> APIRouter:
    """Create read-only audit routes with explicit identity and query dependencies."""
    router = APIRouter(prefix="/api/v1", tags=["audit"])

    @router.get(
        "/properties/{property_id}/audit-events",
        response_model=AuditEventPageResponse,
        summary="Search a property's audit events",
    )
    def search_property_audit_events(
        request: Request,
        property_id: UUID,
        limit: int = Query(DEFAULT_AUDIT_PAGE_SIZE, ge=1, le=MAX_AUDIT_PAGE_SIZE),
        cursor: str | None = Query(None, max_length=512),
        from_date: date | None = None,
        to_date: date | None = None,
        actor_id: UUID | None = None,
        action: str | None = Query(None, max_length=128),
        resource_type: str | None = Query(None, max_length=128),
        resource_id: UUID | None = None,
        customer_id: UUID | None = None,
        unit_id: UUID | None = None,
        lease_id: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> AuditEventPageResponse:
        actor = _require_actor(request, actor_resolver)
        _reject_unknown_filters(
            request,
            {
                "action",
                "actor_id",
                "correlation_id",
                "cursor",
                "customer_id",
                "from_date",
                "lease_id",
                "limit",
                "resource_id",
                "resource_type",
                "to_date",
                "unit_id",
            },
        )
        page = query_flow.search_property(
            actor,
            PropertyAuditQuery(
                property_id=property_id,
                page=AuditPageRequest(limit=limit, cursor=cursor),
                from_date=from_date,
                to_date=to_date,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                customer_id=customer_id,
                unit_id=unit_id,
                lease_id=lease_id,
                correlation_id=correlation_id,
            ),
        )
        return _page_response(page, request.state.request_id)

    @router.get(
        "/{resource_family}/{resource_id}/audit-events",
        response_model=AuditEventPageResponse,
        summary="View a resource's audit timeline",
    )
    def resource_audit_timeline(
        request: Request,
        resource_family: str,
        resource_id: UUID,
        limit: int = Query(DEFAULT_AUDIT_PAGE_SIZE, ge=1, le=MAX_AUDIT_PAGE_SIZE),
        cursor: str | None = Query(None, max_length=512),
    ) -> AuditEventPageResponse:
        actor = _require_actor(request, actor_resolver)
        _reject_unknown_filters(request, {"cursor", "limit"})
        page = query_flow.resource_timeline(
            actor,
            ResourceAuditQuery(
                resource_type=resource_family,
                resource_id=resource_id,
                page=AuditPageRequest(limit=limit, cursor=cursor),
            ),
        )
        return _page_response(page, request.state.request_id)

    return router


def _require_actor(request: Request, actor_resolver: ActorResolver) -> AuthenticatedActor:
    actor = actor_resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _page_response(page: AuditEventPage, request_id: str) -> AuditEventPageResponse:
    return AuditEventPageResponse(
        data=[_event_view(event) for event in page.events],
        meta=AuditPageMeta(request_id=request_id, next_cursor=page.next_cursor),
    )


def _event_view(event: AuditEvent) -> AuditEventView:
    return AuditEventView(
        event_id=event.event_id,
        actor_id=event.actor_id,
        property_id=event.property_id,
        action=_safe_loaded_text(event.action, "action"),
        resource_type=_safe_loaded_text(event.target_type, "entity_type"),
        resource_id=event.target_id,
        occurred_at=event.occurred_at,
        business_date=event.business_date,
        reason=_safe_loaded_text(event.reason, "reason"),
        previous_state=_json_content(_freeze_event_state(event.previous_state, event.target_type)),
        resulting_state=_json_content(
            _freeze_event_state(event.resulting_state, event.target_type)
        ),
        correlation_id=event.correlation_id,
        outcome=_safe_loaded_text(event.outcome, "outcome"),
        source=_safe_loaded_text(event.source, "source"),
        linked_source_event_id=event.linked_source_event_id,
    )


def _json_content(value: AuditValue) -> object:
    """Convert immutable domain snapshots to ordinary JSON containers."""
    if isinstance(value, Mapping):
        return {key: _json_content(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_content(item) for item in value]
    return value


def _freeze_event_state(value: object, entity_type: str) -> AuditValue:
    """Preserve historical Unit floor labels with the existing public-label checks."""
    if entity_type != "unit" or not isinstance(value, Mapping) or "floor" not in value:
        return _freeze_loaded(value)
    floor = value["floor"]
    if not isinstance(floor, str) or not 1 <= len(floor) <= 100 or floor != floor.strip():
        raise ValueError("stored Unit floor is not a canonical text label")
    # Only this canonical top-level Unit attribute uses label classification.
    # All other fields and every nested value retain the existing validation.
    ordinary = _freeze_loaded({key: item for key, item in value.items() if key != "floor"})
    assert isinstance(ordinary, Mapping)
    floor_value = _freeze_loaded(floor, "floor_label")
    return MappingProxyType(
        {key: floor_value if key == "floor" else ordinary[key] for key in value}
    )


def _freeze_loaded(value: object, field_key: str | None = None) -> AuditValue:
    """Freeze trusted historical JSON without applying today's write allowlist."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        _validate_classified_audit_number("stored_audit_value", field_key)
        return value
    if isinstance(value, str):
        if is_file_fingerprint(value, field_key):
            return value
        _reject_secret_text(value, "stored_audit_value")
        _validate_classified_audit_text(value, "stored_audit_value", field_key)
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, AuditValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("stored audit object keys must be strings")
            if _is_forbidden_audit_key(key):
                raise ValueError("stored audit data contains a prohibited secret field")
            frozen[key] = _freeze_loaded(item, key)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_loaded(item, field_key) for item in value)
    raise TypeError("stored audit data must contain only JSON-compatible values")


def _safe_loaded_text(value: object, field_name: str) -> str:
    text = str(value)
    _reject_secret_text(text, f"stored_audit_event.{field_name}")
    return text


def _reject_unknown_filters(request: Request, allowed: set[str]) -> None:
    if any(key not in allowed for key in request.query_params):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
