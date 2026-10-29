"""Tests for property-scoped, read-only audit-event queries."""

import asyncio
import base64
from datetime import UTC, date, datetime
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from property_rental.app import create_app
from property_rental.audit import AuditEvent
from property_rental.audit_api import (
    AUDIT_VIEW_CAPABILITY,
    WITHHELD_REASON,
    AuditEventPage,
    AuditEventQueryRepository,
    AuditPageRequest,
    AuditQueryInvalid,
    AuditQueryUnavailable,
    AuditResourceScopeResolver,
    AuthorizedAuditEventQueryService,
    PostgresAuditEventQueryRepository,
    PostgresAuditResourceScopeResolver,
    PropertyAuditQuery,
    ResolvedAuditResource,
    ResourceAuditQuery,
    _event_view,
    _freeze_loaded,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.settings import Settings

EVENT_ID = UUID("00000000-0000-0000-0000-000000000021")
PROPERTY_ID = UUID("00000000-0000-0000-0000-000000000007")
OTHER_PROPERTY_ID = UUID("00000000-0000-0000-0000-000000000008")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
RESOURCE_ID = UUID("00000000-0000-0000-0000-000000000009")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000004")


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(send())


class RecordingAuditRepository(AuditEventQueryRepository):
    def __init__(self, *, resource_property_id: UUID | None = PROPERTY_ID) -> None:
        self.resource_property_id = resource_property_id
        self.property_queries: list[PropertyAuditQuery] = []
        self.timeline_queries: list[tuple[frozenset[UUID], str, ResourceAuditQuery]] = []

    def search_property(self, query: PropertyAuditQuery) -> AuditEventPage:
        self.property_queries.append(query)
        return AuditEventPage(events=(_event(),), next_cursor="next-page")

    def resource_timeline(
        self,
        *,
        property_ids: frozenset[UUID],
        entity_type: str,
        query: ResourceAuditQuery,
    ) -> AuditEventPage:
        self.timeline_queries.append((property_ids, entity_type, query))
        return AuditEventPage(events=(_event(),))


class RecordingResourceScopeResolver(AuditResourceScopeResolver):
    def __init__(self, *, resource_property_id: UUID | None = PROPERTY_ID) -> None:
        self.resource_property_id = resource_property_id
        self.lookups: list[tuple[str, UUID, frozenset[UUID]]] = []

    def resolve_authorized_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        authorized_property_ids: frozenset[UUID],
    ) -> ResolvedAuditResource | None:
        assert resource_type in {"leases", "occupancies"}
        assert resource_id == RESOURCE_ID
        self.lookups.append((resource_type, resource_id, authorized_property_ids))
        if self.resource_property_id not in authorized_property_ids:
            return None
        return ResolvedAuditResource(
            property_ids=frozenset({self.resource_property_id}),
            entity_type="occupancy" if resource_type == "occupancies" else "lease",
        )


class ScopeCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[object, ...]]:
        return [] if self._row is None else [self._row]


class ScopeConnection:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> ScopeCursor:
        self.calls.append((query, parameters))
        return ScopeCursor(self._row)


def test_postgres_scope_resolver_uses_authoritative_table_and_canonical_entity_type() -> None:
    connection = ScopeConnection((PROPERTY_ID,))
    resolver = PostgresAuditResourceScopeResolver(connection)

    resolved = resolver.resolve_authorized_resource(
        "occupancies",
        RESOURCE_ID,
        frozenset({PROPERTY_ID}),
    )

    assert resolved == ResolvedAuditResource(
        property_ids=frozenset({PROPERTY_ID}),
        entity_type="occupancy",
    )
    query, parameters = connection.calls[0]
    assert "app.occupancies" in query
    assert "app.leases" in query
    assert "app.units" in query
    assert parameters == (RESOURCE_ID, [PROPERTY_ID])


def test_authoritative_reservation_resolves_without_audit_history() -> None:
    connection = ScopeConnection((PROPERTY_ID,))
    resolver = PostgresAuditResourceScopeResolver(connection)

    resolved = resolver.resolve_authorized_resource(
        "reservations",
        RESOURCE_ID,
        frozenset({PROPERTY_ID}),
    )

    assert resolved == ResolvedAuditResource(
        property_ids=frozenset({PROPERTY_ID}),
        entity_type="reservation",
    )
    query, parameters = connection.calls[0]
    assert "app.reservations" in query
    assert "app.units" in query
    assert "app.audit_events" not in query
    assert parameters == (RESOURCE_ID, [PROPERTY_ID])


@pytest.mark.parametrize(
    ("resource_family", "entity_type"),
    [
        ("meters", "utility_meter"),
        ("utility-readings", "utility_reading"),
        ("utility-consumption-periods", "utility_consumption_period"),
        ("rates", "rate"),
        ("invoices", "invoice"),
        ("adjustments", "adjustment"),
        ("late-payment-decisions", "late_payment_decision"),
        ("payments", "payment"),
        ("allocations", "payment_allocation"),
        ("deposits", "deposit"),
        ("refunds", "refund"),
        ("final-settlements", "final_settlement"),
    ],
)
def test_unimplemented_resource_families_never_use_audit_history_as_authority(
    resource_family: str,
    entity_type: str,
) -> None:
    connection = ScopeConnection(None)
    resolver = PostgresAuditResourceScopeResolver(connection)

    with pytest.raises(AuditQueryUnavailable):
        resolver.resolve_authorized_resource(
            resource_family,
            RESOURCE_ID,
            frozenset({PROPERTY_ID}),
        )

    assert entity_type in PostgresAuditResourceScopeResolver._audited_entity_types.values()
    assert connection.calls == []


def _event() -> AuditEvent:
    return AuditEvent(
        event_id=EVENT_ID,
        actor_id=ACTOR_ID,
        property_id=PROPERTY_ID,
        action="lease.created",
        target_type="lease",
        target_id=RESOURCE_ID,
        occurred_at=datetime(2026, 8, 23, 9, 30, tzinfo=UTC),
        business_date=date(2026, 8, 23),
        reason="Lease approved",
        authorization_reference="AUTH-LEASE-001",
        previous_state=None,
        resulting_state={"status": "active"},
        correlation_id=CORRELATION_ID,
        outcome="succeeded",
        source="API",
        authorization_evidence={"capability": AUDIT_VIEW_CAPABILITY},
        linked_source_event_id=None,
    )


def _actor(*property_ids: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id="audit-viewer",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability=AUDIT_VIEW_CAPABILITY,
                    property_ids=frozenset(property_ids),
                )
            }
        ),
    )


def _app(
    repository: RecordingAuditRepository,
    actor: AuthenticatedActor,
    resolver: RecordingResourceScopeResolver | None = None,
) -> FastAPI:
    return create_app(
        Settings(),
        actor_resolver=lambda _: actor,
        audit_query_flow=AuthorizedAuditEventQueryService(
            repository,
            resolver or RecordingResourceScopeResolver(),
        ),
    )


def test_property_search_requires_authentication() -> None:
    response = request(
        create_app(Settings()),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events",
        headers={"X-Request-ID": "audit-unauthenticated"},
    )

    assert response.status_code == 401
    assert response.json()["meta"] == {"request_id": "audit-unauthenticated"}


def test_property_search_requires_dedicated_capability_in_property_scope() -> None:
    repository = RecordingAuditRepository()
    actor = AuthenticatedActor(
        actor_id="ordinary-reader",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability="leases.read",
                    property_ids=frozenset({str(PROPERTY_ID)}),
                )
            }
        ),
    )

    response = request(
        _app(repository, actor),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events",
        headers={"X-Request-ID": "audit-forbidden"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert repository.property_queries == []


def test_property_search_cannot_cross_an_authorized_property_scope() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(OTHER_PROPERTY_ID))),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events",
    )

    assert response.status_code == 403
    assert repository.property_queries == []


def test_property_search_passes_bounded_filters_and_returns_canonical_page() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID))),
        "GET",
        (
            f"/api/v1/properties/{PROPERTY_ID}/audit-events"
            "?limit=25&cursor=current-page&from_date=2026-08-01&to_date=2026-08-31"
            f"&actor_id={ACTOR_ID}&action=lease.created&resource_type=lease"
            f"&resource_id={RESOURCE_ID}&customer_id=00000000-0000-0000-0000-000000000011"
            f"&unit_id=00000000-0000-0000-0000-000000000003"
            f"&lease_id={RESOURCE_ID}&correlation_id={CORRELATION_ID}"
        ),
        headers={"X-Request-ID": "audit-search"},
    )

    assert response.status_code == 200
    query = repository.property_queries[0]
    assert query.property_id == PROPERTY_ID
    assert query.page.limit == 25
    assert query.page.cursor == "current-page"
    assert query.from_date == date(2026, 8, 1)
    assert query.to_date == date(2026, 8, 31)
    assert query.actor_id == ACTOR_ID
    assert query.action == "lease.created"
    assert query.resource_type == "lease"
    assert query.resource_id == RESOURCE_ID
    assert query.customer_id == UUID("00000000-0000-0000-0000-000000000011")
    assert query.unit_id == UUID("00000000-0000-0000-0000-000000000003")
    assert query.lease_id == RESOURCE_ID
    assert query.correlation_id == CORRELATION_ID
    assert response.json() == {
        "data": [
            {
                "event_id": str(EVENT_ID),
                "actor_id": str(ACTOR_ID),
                "property_id": str(PROPERTY_ID),
                "action": "lease.created",
                "resource_type": "lease",
                "resource_id": str(RESOURCE_ID),
                "occurred_at": "2026-08-23T09:30:00Z",
                "business_date": "2026-08-23",
                "reason": "Lease approved",
                "previous_state": None,
                "resulting_state": {"status": "active"},
                "correlation_id": str(CORRELATION_ID),
                "outcome": "succeeded",
                "source": "API",
                "linked_source_event_id": None,
            }
        ],
        "meta": {"request_id": "audit-search", "next_cursor": "next-page"},
    }
    assert "authorization_evidence" not in response.text


def test_search_rejects_an_unbounded_page_before_querying() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID))),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events?limit=101",
    )

    assert response.status_code == 422
    assert repository.property_queries == []


def test_search_rejects_unknown_filters_before_querying() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID))),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events?invented_filter=value",
    )

    assert response.status_code == 400
    assert repository.property_queries == []


def test_search_rejects_reversed_date_range_before_querying() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID))),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events?from_date=2026-08-31&to_date=2026-08-01",
    )

    assert response.status_code == 422
    assert repository.property_queries == []


def test_resource_timeline_resolves_and_authorizes_owning_property() -> None:
    repository = RecordingAuditRepository()
    resolver = RecordingResourceScopeResolver()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID)), resolver),
        "GET",
        f"/api/v1/leases/{RESOURCE_ID}/audit-events?limit=10&cursor=timeline-page",
        headers={"X-Request-ID": "audit-timeline"},
    )

    assert response.status_code == 200
    property_ids, entity_type, query = repository.timeline_queries[0]
    assert property_ids == frozenset({PROPERTY_ID})
    assert entity_type == "lease"
    assert query.resource_type == "leases"
    assert query.resource_id == RESOURCE_ID
    assert query.page.limit == 10
    assert query.page.cursor == "timeline-page"
    assert resolver.lookups == [("leases", RESOURCE_ID, frozenset({PROPERTY_ID}))]
    assert response.json()["meta"] == {
        "request_id": "audit-timeline",
        "next_cursor": None,
    }


def test_resource_timeline_uses_resolver_canonical_irregular_entity_type() -> None:
    repository = RecordingAuditRepository()
    resolver = RecordingResourceScopeResolver()
    app = create_app(
        Settings(),
        actor_resolver=lambda _: _actor(str(PROPERTY_ID)),
        audit_query_flow=AuthorizedAuditEventQueryService(repository, resolver),
    )

    response = request(
        app,
        "GET",
        f"/api/v1/occupancies/{RESOURCE_ID}/audit-events",
    )

    assert response.status_code == 200
    assert repository.timeline_queries[0][1] == "occupancy"


def test_resource_timeline_does_not_query_events_outside_property_scope() -> None:
    repository = RecordingAuditRepository()
    resolver = RecordingResourceScopeResolver()

    response = request(
        _app(repository, _actor(str(OTHER_PROPERTY_ID)), resolver),
        "GET",
        f"/api/v1/leases/{RESOURCE_ID}/audit-events",
    )

    assert response.status_code == 404
    assert repository.timeline_queries == []
    assert resolver.lookups == [("leases", RESOURCE_ID, frozenset({OTHER_PROPERTY_ID}))]


def test_unknown_resource_returns_canonical_not_found() -> None:
    repository = RecordingAuditRepository()
    resolver = RecordingResourceScopeResolver(resource_property_id=None)

    response = request(
        _app(repository, _actor(str(PROPERTY_ID)), resolver),
        "GET",
        f"/api/v1/leases/{RESOURCE_ID}/audit-events",
        headers={"X-Request-ID": "audit-not-found"},
    )

    assert response.status_code == 404
    assert response.json()["meta"] == {"request_id": "audit-not-found"}


def test_audit_routes_expose_no_mutation_api() -> None:
    repository = RecordingAuditRepository()

    response = request(
        _app(repository, _actor(str(PROPERTY_ID))),
        "DELETE",
        f"/api/v1/properties/{PROPERTY_ID}/audit-events",
    )

    assert response.status_code == 405
    assert repository.property_queries == []


def test_customer_scope_resolver_collects_all_authorized_related_properties() -> None:
    class MultiRowConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> ScopeCursor:
            self.calls.append((query, parameters))
            cursor = ScopeCursor(None)
            cursor.fetchall = lambda: [(PROPERTY_ID,), (OTHER_PROPERTY_ID,)]  # type: ignore[method-assign]
            return cursor

    connection = MultiRowConnection()
    resolver = PostgresAuditResourceScopeResolver(connection)

    resolved = resolver.resolve_authorized_resource(
        "customers",
        RESOURCE_ID,
        frozenset({PROPERTY_ID, OTHER_PROPERTY_ID}),
    )

    assert resolved == ResolvedAuditResource(
        property_ids=frozenset({PROPERTY_ID, OTHER_PROPERTY_ID}),
        entity_type="customer",
    )
    query, parameters = connection.calls[0]
    assert "app.reservations" in query
    assert "app.lease_signers" in query
    assert "app.occupancies" in query
    assert "app.audit_events" not in query
    assert parameters == (
        RESOURCE_ID,
        RESOURCE_ID,
        RESOURCE_ID,
        RESOURCE_ID,
        [PROPERTY_ID, OTHER_PROPERTY_ID],
    )


class QueryCursor:
    def fetchone(self) -> tuple[object, ...] | None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class QueryConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> QueryCursor:
        self.calls.append((query, parameters))
        return QueryCursor()


def test_resource_timeline_includes_linked_lease_events_across_authorized_properties() -> None:
    connection = QueryConnection()
    repository = PostgresAuditEventQueryRepository(connection)

    repository.resource_timeline(
        property_ids=frozenset({PROPERTY_ID, OTHER_PROPERTY_ID}),
        entity_type="lease",
        query=ResourceAuditQuery(
            resource_type="leases",
            resource_id=RESOURCE_ID,
            page=AuditPageRequest(limit=10),
        ),
    )

    query, parameters = connection.calls[0]
    assert "property_id = ANY(%s::uuid[])" in query
    assert "lease_id = %s" in query
    assert parameters[:4] == (
        [PROPERTY_ID, OTHER_PROPERTY_ID],
        "lease",
        RESOURCE_ID,
        RESOURCE_ID,
    )


def test_cursor_rejects_naive_timestamp_and_normalizes_aware_timestamp() -> None:
    connection = QueryConnection()
    repository = PostgresAuditEventQueryRepository(connection)
    naive = (
        base64.urlsafe_b64encode(f"2026-08-23T09:30:00|{EVENT_ID}".encode()).decode().rstrip("=")
    )

    with pytest.raises(AuditQueryInvalid):
        repository.search_property(
            PropertyAuditQuery(
                property_id=PROPERTY_ID,
                page=AuditPageRequest(cursor=naive),
            )
        )

    aware = (
        base64.urlsafe_b64encode(f"2026-08-23T16:30:00+07:00|{EVENT_ID}".encode())
        .decode()
        .rstrip("=")
    )
    repository.search_property(
        PropertyAuditQuery(
            property_id=PROPERTY_ID,
            page=AuditPageRequest(cursor=aware),
        )
    )

    assert connection.calls[0][1][-3] == datetime(2026, 8, 23, 9, 30, tzinfo=UTC)


def test_loaded_historical_public_facts_are_classified_and_frozen() -> None:
    loaded = _freeze_loaded(
        {
            "calculation": {
                "rounding_rule": "ROUND_HALF_UP",
                "basis_points": 2000,
            },
            "settlement_inputs": {"original_currency": "USD"},
        }
    )

    assert loaded == {
        "calculation": {"rounding_rule": "ROUND_HALF_UP", "basis_points": 2000},
        "settlement_inputs": {"original_currency": "USD"},
    }
    with pytest.raises(TypeError):
        loaded["calculation"] = None


def test_loaded_camel_case_classified_key_uses_write_normalization() -> None:
    customer_id = "00000000-0000-0000-0000-000000000011"

    loaded = _freeze_loaded({"customerId": customer_id})

    assert loaded == {"customerId": customer_id}


def test_stored_top_level_secret_material_is_rejected_before_event_exposure() -> None:
    row: tuple[object, ...] = (
        EVENT_ID,
        ACTOR_ID,
        "lease.created",
        "lease",
        RESOURCE_ID,
        datetime(2026, 8, 23, 9, 30, tzinfo=UTC),
        date(2026, 8, 23),
        "password=hunter2",
        "AUTH-LEASE-001",
        None,
        {"status": "active"},
        CORRELATION_ID,
        "API",
        PROPERTY_ID,
        "succeeded",
        {"capability": AUDIT_VIEW_CAPABILITY},
        None,
        None,
        None,
        RESOURCE_ID,
    )

    with pytest.raises(ValueError, match="prohibited secret material"):
        PostgresAuditEventQueryRepository._event(row)


def stored_row(
    *,
    action: str = "payment.confirmed",
    entity_type: str = "payment",
    reason: str = "Payment confirmed",
    reference: str | None = "payments.confirm",
    state: object = None,
    evidence: object = None,
) -> tuple[object, ...]:
    return (
        EVENT_ID,
        ACTOR_ID,
        action,
        entity_type,
        RESOURCE_ID,
        datetime(2026, 10, 28, 3, 45, tzinfo=UTC),
        date(2026, 10, 28),
        reason,
        reference,
        None,
        state,
        CORRELATION_ID,
        "API",
        PROPERTY_ID,
        "SUCCEEDED",
        evidence,
        None,
        None,
        None,
        None,
    )


def test_a_stored_event_with_unclassified_details_shows_with_them_withheld() -> None:
    # V1-060 B6: the History page failed on almost every real money event, because their
    # stored states hold values today's public-value checks do not classify.
    row = stored_row(
        state={"event": "Payment confirmed", "received_amount_minor": 30500},
        evidence={"one_time_code": "A1B2C3D4"},
    )
    with pytest.raises(ValueError):
        PostgresAuditEventQueryRepository._event(row)

    page = PostgresAuditEventQueryRepository._page([row], 50)

    (event,) = page.events
    assert (event.action, event.target_type, event.reason) == (
        "payment.confirmed",
        "payment",
        "Payment confirmed",
    )
    assert event.previous_state is None and event.resulting_state is None
    assert event.authorization_evidence is None
    assert event.authorization_reference == "payments.confirm"
    view = _event_view(event)
    assert view.previous_state is None and view.resulting_state is None
    assert view.reason == "Payment confirmed"


def test_a_stored_reason_or_reference_that_looks_like_a_secret_is_replaced() -> None:
    row = stored_row(reason="password=hunter2", reference="password=hunter2")

    (event,) = PostgresAuditEventQueryRepository._page([row], 50).events

    assert event.reason == WITHHELD_REASON
    assert event.authorization_reference is None
    assert "hunter2" not in repr(_event_view(event))


def test_a_long_app_code_shows_as_the_action_and_resource_type() -> None:
    # The DL-101 event's entity type is 34 lowercase letters and underscores, which the generic
    # long-run secret pattern took for a secret.
    row = stored_row(
        action="lease.security_deposit.applied",
        entity_type="deposit_required_amount_adjustment",
        reason="Security Deposit on the signed Lease",
        reference="leases.sign",
        state={"status": "APPLIED"},
    )

    event = PostgresAuditEventQueryRepository._event(row)
    view = _event_view(event)

    assert view.resource_type == "deposit_required_amount_adjustment"
    assert view.resulting_state == {"status": "APPLIED"}
    secretish = stored_row(entity_type="Ab1" * 12)
    with pytest.raises(ValueError, match="prohibited secret material"):
        PostgresAuditEventQueryRepository._event(secretish)


@pytest.mark.parametrize(
    "secret_key",
    [
        "access_code",
        "otp",
        "otp_value",
        "pin",
        "pin_number",
        "pwd",
        "pwd_value",
        "reset_code",
        "verification_code",
    ],
)
def test_stored_numeric_secret_fields_are_rejected_before_exposure(secret_key: str) -> None:
    with pytest.raises(ValueError, match="prohibited secret field"):
        _freeze_loaded({"account": {secret_key: 123456}})


@pytest.mark.parametrize("value", [123456, "123456"])
def test_stored_unclassified_numeric_authentication_secret_is_not_exposed(
    value: object,
) -> None:
    with pytest.raises(ValueError, match="numeric value is not an approved public"):
        _freeze_loaded({"account": {"one_time_code": value}})


def test_stored_unclassified_text_authentication_secret_is_not_exposed() -> None:
    with pytest.raises(ValueError, match="not an approved public audit value"):
        _freeze_loaded({"account": {"one_time_code": "A1B2C3D4"}})


def unit_floor_audit_row(state: object, entity_type: str = "unit") -> tuple[object, ...]:
    return (
        EVENT_ID,
        ACTOR_ID,
        "unit.updated",
        entity_type,
        RESOURCE_ID,
        datetime(2026, 8, 23, 9, 30, tzinfo=UTC),
        date(2026, 8, 23),
        "Parking readiness confirmed",
        None,
        state,
        state,
        CORRELATION_ID,
        "API",
        PROPERTY_ID,
        "SUCCEEDED",
        None,
        None,
        None,
        RESOURCE_ID,
        None,
    )


@pytest.mark.parametrize("floor", ["1", "G", "Basement", "2B"])
def test_historical_unit_floor_round_trips_without_rewriting_state(floor: str) -> None:
    state = {
        "unit_id": str(RESOURCE_ID),
        "property_id": str(PROPERTY_ID),
        "unit_number": "101",
        "floor": floor,
        "unit_type": "UNCOVERED",
        "status": "VACANT",
        "version": 2,
    }
    row = unit_floor_audit_row(state)
    event = PostgresAuditEventQueryRepository._event(row)
    view = _event_view(event)
    assert event.previous_state == event.resulting_state == state
    assert view.previous_state == view.resulting_state == state
    assert state["floor"] == floor and row[9] is state
    with pytest.raises(ValueError):
        _freeze_loaded({"floor": floor})


@pytest.mark.parametrize(
    "floor",
    [None, 1, True, "", " 1", "1\n", "x" * 101, {"label": "1"}, "password=synthetic-fixture"],
)
def test_unit_floor_compatibility_retains_value_rejections(floor: object) -> None:
    with pytest.raises(ValueError):
        PostgresAuditEventQueryRepository._event(unit_floor_audit_row({"floor": floor}))


@pytest.mark.parametrize("entity_type", ["property", "physical_move_out"])
def test_floor_label_compatibility_is_limited_to_unit_events(entity_type: str) -> None:
    with pytest.raises(ValueError):
        PostgresAuditEventQueryRepository._event(unit_floor_audit_row({"floor": "1"}, entity_type))


def test_unit_floor_compatibility_does_not_reclassify_nested_fields() -> None:
    with pytest.raises(ValueError):
        PostgresAuditEventQueryRepository._event(unit_floor_audit_row({"details": {"floor": "1"}}))


def test_unit_floor_compatibility_preserves_other_field_validation() -> None:
    with pytest.raises(ValueError):
        PostgresAuditEventQueryRepository._event(
            unit_floor_audit_row({"floor": "1", "one_time_code": 123456})
        )
