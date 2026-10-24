"""Contract tests for Customer resources, privacy, and preserved history."""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.customer import (
    Customer,
    CustomerIdNumberInUse,
    CustomerReuseRequired,
    CustomerVersionConflict,
    id_document_match_key,
)
from property_rental.customer_api import (
    CustomerCommandIdentityConflict,
    CustomerCommandStatus,
    CustomerHistoryEvent,
    CustomerHistoryPage,
    CustomerIdempotencyKeyReused,
    CustomerLifecycleConflict,
    CustomerPage,
    CustomerRecord,
    CustomerResourceInvalid,
    CustomerResourceNotFound,
    CustomerResourceUnavailable,
    PostgresCustomerResourceFlow,
    SlidingWindowCustomerSearchRateGuard,
    _decode_history_cursor,
    _encode_history_cursor,
    _record,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


@dataclass(slots=True)
class InMemoryCustomerFlow:
    property_id: UUID
    customers: dict[UUID, CustomerRecord] = field(default_factory=dict)
    events: dict[UUID, tuple[CustomerHistoryEvent, ...]] = field(default_factory=dict)
    force_reuse: bool = False
    detail_calls: int = 0
    commands: dict[UUID, tuple[str, str, CustomerRecord]] = field(default_factory=dict)

    def record_event(
        self,
        customer_id: UUID,
        *,
        actor_id: str,
        action: str,
        reason: str,
        previous_state: object | None,
        resulting_state: object | None,
        event_id: UUID,
    ) -> None:
        event = CustomerHistoryEvent(
            event_id=event_id,
            occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
            actor_id=UUID(actor_id),
            action=action,
            reason=reason,
            previous_state=previous_state,
            resulting_state=resulting_state,
            correlation_id=event_id,
            outcome="SUCCEEDED",
        )
        self.events[customer_id] = (event, *self.events.get(customer_id, ()))

    def list(
        self,
        property_id: UUID,
        *,
        query: str | None,
        active: bool | None,
        limit: int,
        cursor: str | None,
    ) -> CustomerPage:
        del query, cursor
        if property_id != self.property_id:
            raise CustomerResourceNotFound
        records = tuple(
            record
            for record in self.customers.values()
            if active is None or record.active is active
        )
        return CustomerPage(records[:limit], None)

    def get(self, customer_id: UUID) -> CustomerRecord:
        try:
            return self.customers[customer_id]
        except KeyError as exc:
            raise CustomerResourceNotFound from exc

    def detail(
        self,
        customer_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[CustomerRecord, CustomerHistoryPage]:
        self.detail_calls += 1
        record = self.get(customer_id)
        return record, self.history(
            customer_id,
            property_id=record.property_id,
            limit=limit,
            cursor=cursor,
        )

    def create(
        self,
        property_id: UUID,
        *,
        customer_id: UUID,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        existing_command = self.commands.get(idempotency_key)
        if existing_command is not None:
            action, digest, record = existing_command
            if action != "create" or digest != request_digest:
                raise CustomerIdempotencyKeyReused
            return record
        if property_id != self.property_id:
            raise CustomerResourceNotFound
        customer = Customer(
            customer_id,
            legal_name,
            phone_number,
            email_address,
            contact_address,
            memo,
            id_document_number=id_document_number,
        )
        holder = next(
            (
                record.customer
                for record in self.customers.values()
                if record.customer.customer_id != customer_id
                and id_document_match_key(record.customer.id_document_number)
                == id_document_match_key(id_document_number)
            ),
            None,
        )
        if holder is not None:
            raise CustomerIdNumberInUse(holder)
        existing = self.customers.get(customer_id)
        if existing is not None:
            if existing.property_id == property_id and existing.customer == customer:
                return existing
            raise CustomerCommandIdentityConflict("Customer command identity was already used")
        if self.force_reuse and not confirmed_distinct:
            raise CustomerReuseRequired((next(iter(self.customers.values())).customer,))
        record = CustomerRecord(customer, property_id)
        self.customers[customer.customer_id] = record
        self.record_event(
            customer.customer_id,
            actor_id=actor_id,
            action="customer.created",
            reason="Canonical Customer identity created",
            previous_state=None,
            resulting_state={"customer_id": str(customer.customer_id), "version": 1},
            event_id=idempotency_key,
        )
        self.commands[idempotency_key] = ("create", request_digest, record)
        return record

    def update(
        self,
        customer_id: UUID,
        *,
        legal_name: str,
        phone_number: str | None,
        email_address: str | None,
        contact_address: str | None,
        memo: str | None,
        confirmed_distinct: bool,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
        id_document_number: str | None = None,
    ) -> CustomerRecord:
        existing_command = self.commands.get(idempotency_key)
        if existing_command is not None:
            action, digest, record = existing_command
            if action != "update" or digest != request_digest:
                raise CustomerIdempotencyKeyReused
            return record
        del confirmed_distinct
        current = self.get(customer_id)
        if current.customer.version != expected_version:
            raise CustomerVersionConflict(current.customer.version)
        if not current.active:
            raise CustomerLifecycleConflict(current.customer.version)
        id_number = (
            current.customer.id_document_number
            if id_document_number is None
            else id_document_number
        )
        if (
            legal_name,
            phone_number,
            email_address,
            contact_address,
            memo,
            id_number,
        ) == (
            current.customer.legal_name,
            current.customer.phone_number,
            current.customer.email_address,
            current.customer.contact_address,
            current.customer.memo,
            current.customer.id_document_number,
        ):
            raise CustomerResourceInvalid("Customer update must change source data")
        try:
            updated_customer = Customer(
                customer_id,
                legal_name,
                phone_number,
                email_address,
                contact_address,
                memo,
                current.customer.version + 1,
                id_number,
                _allow_legacy_phone=phone_number == current.customer.phone_number,
            )
        except ValueError as exc:
            raise CustomerResourceInvalid("Customer source fields are invalid") from exc
        updated = replace(current, customer=updated_customer)
        self.customers[customer_id] = updated
        self.record_event(
            customer_id,
            actor_id=actor_id,
            action="customer.updated",
            reason="Current Customer contact values updated without changing identity",
            previous_state={"version": current.customer.version},
            resulting_state={"version": updated.customer.version},
            event_id=idempotency_key,
        )
        self.commands[idempotency_key] = ("update", request_digest, updated)
        return updated

    def deactivate(
        self,
        customer_id: UUID,
        *,
        reason: str,
        expected_version: int,
        actor_id: str,
        idempotency_key: UUID,
        request_digest: str,
    ) -> CustomerRecord:
        existing_command = self.commands.get(idempotency_key)
        if existing_command is not None:
            action, digest, record = existing_command
            if action != "deactivate" or digest != request_digest:
                raise CustomerIdempotencyKeyReused
            return record
        current = self.get(customer_id)
        if current.customer.version != expected_version:
            raise CustomerVersionConflict(current.customer.version)
        if not current.active:
            raise CustomerLifecycleConflict(current.customer.version)
        updated = replace(
            current,
            customer=replace(current.customer, version=current.customer.version + 1),
            deactivated_at=datetime(2026, 8, 24, tzinfo=UTC),
            deactivation_reason=reason,
        )
        self.customers[customer_id] = updated
        self.record_event(
            customer_id,
            actor_id=actor_id,
            action="customer.deactivated",
            reason=reason,
            previous_state={"active": True, "version": current.customer.version},
            resulting_state={"active": False, "version": updated.customer.version},
            event_id=idempotency_key,
        )
        self.commands[idempotency_key] = ("deactivate", request_digest, updated)
        return updated

    def command_status(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        action: str,
        idempotency_key: UUID,
        actor_id: str,
        request_digest: str | None = None,
    ) -> CustomerCommandStatus:
        del actor_id
        if property_id != self.property_id:
            raise CustomerResourceNotFound
        command = self.commands.get(idempotency_key)
        if command is None:
            return CustomerCommandStatus(False, None)
        stored_action, stored_digest, record = command
        if (
            stored_action != action
            or record.customer.customer_id != customer_id
            or (request_digest is not None and stored_digest != request_digest)
        ):
            raise CustomerIdempotencyKeyReused
        return CustomerCommandStatus(True, record, idempotency_key)

    def command_history(
        self,
        *,
        property_id: UUID,
        customer_id: UUID,
        event_id: UUID,
    ) -> CustomerHistoryPage:
        page = self.history(customer_id, property_id=property_id, limit=100, cursor=None)
        return CustomerHistoryPage(
            tuple(event for event in page.items if event.event_id == event_id), None
        )

    def history(
        self,
        customer_id: UUID,
        *,
        property_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> CustomerHistoryPage:
        self.get(customer_id)
        if property_id != self.property_id:
            raise CustomerResourceNotFound
        offset = 0 if cursor is None else int(cursor)
        events = self.events.get(customer_id, ())
        page = events[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(events) else None
        return CustomerHistoryPage(page, next_cursor)

    def financial_summary(
        self,
        customer_id: UUID,
        *,
        deposit_limit: int,
        deposit_cursor: str | None,
    ) -> dict[str, object]:
        del deposit_limit, deposit_cursor
        self.get(customer_id)
        return {
            "source_status": "UNAVAILABLE_UNTIL_FINANCIAL_SOURCES_ARE_IMPLEMENTED",
            "source_availability": {
                "deposits": "UNAVAILABLE_NOT_IMPLEMENTED",
                "invoices": "UNAVAILABLE_NOT_IMPLEMENTED",
                "late_charges": "UNAVAILABLE_NOT_IMPLEMENTED",
                "payments": "UNAVAILABLE_NOT_IMPLEMENTED",
                "customer_credit": "UNAVAILABLE_NOT_IMPLEMENTED",
            },
            "currency_summaries": [],
            "deposit_liabilities": [],
            "deposit_liabilities_page": {"next_cursor": None, "limit": 50},
            "deposit_aggregate": {
                "count": 0,
                "required_usd_cents": 0,
                "received_usd_cents": 0,
                "held_refundable_usd_cents": 0,
                "outstanding_required_usd_cents": 0,
            },
            "customer_credit_is_separate_from_deposit": True,
        }


def manager(property_id: UUID, *, audit: bool = False) -> AuthenticatedActor:
    grants = {
        CapabilityGrant(
            capability="customers.manage",
            property_ids=frozenset({str(property_id)}),
        )
    }
    if audit:
        grants.add(
            CapabilityGrant(
                capability="audit.view",
                property_ids=frozenset({str(property_id)}),
            )
        )
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(grants),
    )


def reader(property_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability="customers.read",
                    property_ids=frozenset({str(property_id)}),
                )
            }
        ),
    )


def mutation_headers(version: int | None = None) -> dict[str, str]:
    return {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf-token",
        "Cookie": "__Host-prm_csrf=csrf-token",
        "Idempotency-Key": str(uuid4()),
        **({} if version is None else {"If-Match": f'"{version}"'}),
    }


def sample_record(property_id: UUID) -> CustomerRecord:
    return CustomerRecord(
        Customer(
            uuid4(),
            "Dara Sok",
            "012345678",
            "dara@example.com",
            "Phnom Penh",
            "Contact after 17:00",
        ),
        property_id,
    )


def test_api_hydration_preserves_a_legacy_phone_for_correction() -> None:
    customer_id = uuid4()
    property_id = uuid4()

    record = _record(
        (
            customer_id,
            "Legacy Customer",
            "012/345",
            None,
            None,
            None,
            1,
            None,
            None,
            property_id,
        )
    )

    assert record.customer.phone_number == "012/345"


def test_api_hydration_accepts_revision_15_boundary_whitespace() -> None:
    customer_id = uuid4()
    property_id = uuid4()

    record = _record(
        (
            customer_id,
            "\tLegacy Customer\u00a0",
            "\t012/345\u00a0",
            "\tlegacy@example.com\u00a0",
            "\u00a0Historic address\t",
            "\tHistoric memo\u00a0",
            1,
            None,
            None,
            property_id,
        )
    )

    assert record.customer.legal_name == "\tLegacy Customer\u00a0"
    assert record.customer.phone_number == "\t012/345\u00a0"
    assert record.customer.email_address == "\tlegacy@example.com\u00a0"
    assert record.customer.contact_address == "\u00a0Historic address\t"
    assert record.customer.memo == "\tHistoric memo\u00a0"


def test_customer_patch_preserves_an_unchanged_legacy_phone() -> None:
    customer_id = uuid4()
    property_id = uuid4()
    record = CustomerRecord(
        Customer(
            customer_id,
            "Legacy Customer",
            "012/345",
            _allow_legacy_phone=True,
        ),
        property_id,
    )
    flow = InMemoryCustomerFlow(property_id, {customer_id: record})
    client = TestClient(
        create_app(
            actor_resolver=lambda _: manager(property_id),
            customer_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=mutation_headers(1),
        json={"phone_number": "012/345", "memo": "Corrected memo"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["phone_number"] == "012/345"
    assert response.json()["data"]["memo"] == "Corrected memo"

    invalid_replacement = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=mutation_headers(2),
        json={"phone_number": "999/999"},
    )
    assert invalid_replacement.status_code == 422


def test_customer_list_is_authenticated_minimized_and_capability_sensitive() -> None:
    property_id = uuid4()
    record = sample_record(property_id)
    flow = InMemoryCustomerFlow(property_id, {record.customer.customer_id: record})

    assert (
        TestClient(create_app(customer_resource_flow=flow))
        .get(f"/api/v1/properties/{property_id}/customers")
        .status_code
        == 401
    )

    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), customer_resource_flow=flow)
    )
    response = client.get(f"/api/v1/properties/{property_id}/customers?limit=10&active=true")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert response.json()["meta"]["can_manage"] is True
    assert response.json()["page"] == {"next_cursor": None, "limit": 10}
    assert response.json()["data"] == [
        {
            "customer_id": str(record.customer.customer_id),
            "legal_name": "Dara Sok",
            "active": True,
            "relationship_indicators": [],
        }
    ]
    assert "email_address" not in response.text
    assert "phone_number" not in response.text
    assert (
        client.get(f"/api/v1/properties/{property_id}/customers?customer_type=TENANT").status_code
        == 400
    )
    assert (
        client.get(f"/api/v1/properties/{property_id}/customers?cursor={'x' * 513}").status_code
        == 422
    )
    assert client.get(f"/api/v1/properties/{property_id}/customers?query=%00").status_code == 422
    assert client.get(f"/properties/{property_id}/customers").status_code == 404


def test_customer_create_requires_scope_and_an_explicit_reuse_decision() -> None:
    property_id = uuid4()
    existing = sample_record(property_id)
    flow = InMemoryCustomerFlow(
        property_id, {existing.customer.customer_id: existing}, force_reuse=True
    )
    payload: dict[str, object] = {
        "customer_id": str(uuid4()),
        "id_document_number": f"P {uuid4().hex[:8]}",
        "legal_name": "Dara S.",
        "email_address": "dara@example.com",
    }
    reader = TestClient(
        create_app(
            actor_resolver=lambda _: AuthenticatedActor(actor_id=str(uuid4())),
            customer_resource_flow=flow,
        )
    )

    assert (
        reader.post(
            f"/api/v1/properties/{property_id}/customers",
            json=payload,
            headers=mutation_headers(),
        ).status_code
        == 403
    )

    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), customer_resource_flow=flow)
    )
    assert (
        client.post(f"/api/v1/properties/{property_id}/customers", json=payload).status_code == 403
    )
    conflict = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json=payload,
        headers=mutation_headers(),
    )
    assert conflict.status_code == 409
    assert conflict.headers["cache-control"] == "private, no-store"
    assert conflict.headers["vary"] == "Cookie"
    assert conflict.json()["error"]["reuse_candidates"] == [
        {
            "customer_id": str(existing.customer.customer_id),
            "legal_name": "Dara Sok",
        }
    ]
    payload["confirmed_distinct"] = True
    create_headers = mutation_headers()
    created = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json=payload,
        headers=create_headers,
    )

    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    assert (
        created.headers["location"] == f"/api/v1/customers/{created.json()['data']['customer_id']}"
    )
    assert created.json()["data"]["legal_name"] == "Dara S."
    replay = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json={
            **payload,
            "legal_name": "  Dara S.  ",
            "email_address": "  dara@example.com  ",
        },
        headers=create_headers,
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["customer_id"] == created.json()["data"]["customer_id"]
    assert replay.json()["data"] == created.json()["data"]
    assert len(flow.customers) == 2

    boundary_payload = {
        "customer_id": str(uuid4()),
        "id_document_number": f"P {uuid4().hex[:8]}",
        "legal_name": "x" * 255,
        "confirmed_distinct": True,
    }
    boundary_headers = mutation_headers()
    boundary_created = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json=boundary_payload,
        headers=boundary_headers,
    )
    assert boundary_created.status_code == 201
    boundary_replay = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json={**boundary_payload, "legal_name": f"  {boundary_payload['legal_name']}  "},
        headers=boundary_headers,
    )
    assert boundary_replay.status_code == 201
    assert boundary_replay.json()["data"] == boundary_created.json()["data"]
    conflicting_replay = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json={**payload, "legal_name": "Different command input"},
        headers=create_headers,
    )
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert conflicting_replay.json()["error"]["rule_ids"] == ["API-016"]
    assert len(flow.customers) == 3
    customer_id_collision = client.post(
        f"/api/v1/properties/{property_id}/customers",
        json={**payload, "legal_name": "Different identity collision"},
        headers=mutation_headers(),
    )
    assert customer_id_collision.status_code == 409
    assert customer_id_collision.json()["error"]["code"] == "CONFLICT"
    assert (
        client.post(
            f"/api/v1/properties/{property_id}/customers",
            json={
                "customer_id": str(uuid4()),
                "id_document_number": f"P {uuid4().hex[:8]}",
                "legal_name": "Malformed",
                "confirmed_distinct": "yes",
            },
            headers=mutation_headers(),
        ).status_code
        == 422
    )
    for invalid_payload in (
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Invalid\x00Name",
        },
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Invalid phone",
            "phone_number": "١٢٣",
        },
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Invalid phone",
            "phone_number": "012/345",
        },
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Unicode email domain requires ASCII IDN input",
            "email_address": "user@bücher.de",
        },
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Unsupported email local punctuation",
            "email_address": "user,name@example.com",
        },
        {
            "customer_id": str(uuid4()),
            "id_document_number": f"P {uuid4().hex[:8]}",
            "legal_name": "Unsupported email local control",
            "email_address": "user\x01name@example.com",
        },
    ):
        assert (
            client.post(
                f"/api/v1/properties/{property_id}/customers",
                json=invalid_payload,
                headers=mutation_headers(),
            ).status_code
            == 422
        )
    surrogate_response = client.post(
        f"/api/v1/properties/{property_id}/customers",
        content=json.dumps(
            {
                "customer_id": str(uuid4()),
                "id_document_number": f"P {uuid4().hex[:8]}",
                "legal_name": "Invalid\ud800Name",
            },
            ensure_ascii=True,
        ),
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    assert surrogate_response.status_code == 422
    assert (
        client.post(
            f"/api/v1/properties/{property_id}/customers",
            json={
                "customer_id": str(uuid4()),
                "id_document_number": f"P {uuid4().hex[:8]}",
                "legal_name": "Invalid",
                "customer_type": "TENANT",
            },
            headers=mutation_headers(),
        ).status_code
        == 422
    )


def test_customer_create_command_status_authoritatively_reports_present_or_absent() -> None:
    property_id = uuid4()
    record = sample_record(property_id)
    command_id = uuid4()
    flow = InMemoryCustomerFlow(
        property_id,
        {record.customer.customer_id: record},
        commands={command_id: ("create", "digest", record)},
    )
    path = (
        f"/api/v1/properties/{property_id}/customers/{record.customer.customer_id}/command-status"
        f"?action=create&idempotency_key={command_id}"
    )

    assert TestClient(create_app(customer_resource_flow=flow)).get(path).status_code == 401
    reader_client = TestClient(
        create_app(
            actor_resolver=lambda _: reader(property_id),
            customer_resource_flow=flow,
        )
    )
    assert reader_client.get(path).status_code == 403

    client = TestClient(
        create_app(
            actor_resolver=lambda _: manager(property_id),
            customer_resource_flow=flow,
        )
    )
    present = client.get(path)
    assert present.status_code == 200
    assert present.headers["cache-control"] == "private, no-store"
    assert present.headers["vary"] == "Cookie"
    assert present.json()["data"]["recorded"] is True
    assert present.json()["data"]["customer"]["customer_id"] == str(record.customer.customer_id)
    reused = client.get(
        f"/api/v1/properties/{property_id}/customers/{uuid4()}/command-status"
        f"?action=create&idempotency_key={command_id}"
    )
    assert reused.status_code == 409
    absent = client.get(
        f"/api/v1/properties/{property_id}/customers/{uuid4()}/command-status"
        f"?action=create&idempotency_key={uuid4()}"
    )
    assert absent.status_code == 200
    assert absent.json()["data"] == {
        "recorded": False,
        "expired": False,
        "customer": None,
    }
    assert client.get(f"{path}&unexpected=true").status_code == 400

    missing_property = uuid4()
    missing = TestClient(
        create_app(
            actor_resolver=lambda _: manager(missing_property),
            customer_resource_flow=flow,
        )
    ).get(
        f"/api/v1/properties/{missing_property}/customers/{uuid4()}/command-status"
        f"?action=create&idempotency_key={uuid4()}"
    )
    assert missing.status_code == 404


def test_customer_detail_update_and_deactivation_preserve_identity_and_history() -> None:
    property_id = uuid4()
    record = sample_record(property_id)
    event = CustomerHistoryEvent(
        event_id=uuid4(),
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        actor_id=uuid4(),
        action="customer.created",
        reason="Authorized Customer creation",
        previous_state=None,
        resulting_state={"customer_id": str(record.customer.customer_id)},
        correlation_id=uuid4(),
        outcome="SUCCEEDED",
    )
    older_event = replace(
        event,
        event_id=uuid4(),
        occurred_at=datetime(2026, 8, 23, tzinfo=UTC),
        action="customer.imported",
        correlation_id=uuid4(),
    )
    flow = InMemoryCustomerFlow(
        property_id,
        {record.customer.customer_id: record},
        {record.customer.customer_id: (event, older_event)},
    )
    client = TestClient(
        create_app(
            actor_resolver=lambda _: manager(property_id, audit=True),
            customer_resource_flow=flow,
        )
    )

    detail = client.get(f"/api/v1/customers/{record.customer.customer_id}")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "private, no-store"
    assert detail.headers["vary"] == "Cookie"
    assert detail.json()["data"]["audit_history"][0]["action"] == "customer.created"
    assert set(detail.json()["data"]["relationships"]) == {
        "reservations",
        "primary_tenant_leases",
        "signer_leases",
        "occupancies",
        "invoices",
        "payments",
        "customer_credit",
        "refunds",
    }
    first_history_page = client.get(
        f"/api/v1/customers/{record.customer.customer_id}?history_limit=1"
    )
    history_cursor = first_history_page.json()["data"]["audit_history_next_cursor"]
    assert history_cursor == "1"
    older_history_page = client.get(
        f"/api/v1/customers/{record.customer.customer_id}"
        f"?history_limit=1&history_cursor={history_cursor}"
    )
    assert older_history_page.json()["data"]["audit_history"][0]["action"] == "customer.imported"
    assert older_history_page.json()["data"]["audit_history_next_cursor"] is None

    stale = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(0),
        json={"memo": None},
    )
    assert stale.status_code == 412

    weak_precondition = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers={**mutation_headers(), "If-Match": 'W/"1"'},
        json={"memo": None},
    )
    assert weak_precondition.status_code == 412

    malformed_precondition = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers={**mutation_headers(), "If-Match": "not-a-version"},
        json={"memo": None},
    )
    assert malformed_precondition.status_code == 412

    for out_of_range_version in (0, 2_147_483_648, -2_147_483_649):
        out_of_range = client.patch(
            f"/api/v1/customers/{record.customer.customer_id}",
            headers={
                **mutation_headers(),
                "If-Match": f'"{out_of_range_version}"',
            },
            json={"memo": None},
        )
        assert out_of_range.status_code == 412

    missing_precondition = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(),
        json={"memo": None},
    )
    assert missing_precondition.status_code == 412

    noop = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(1),
        json={"legal_name": "  Dara Sok  ", "phone_number": " 012345678 "},
    )
    assert noop.status_code == 422
    assert flow.get(record.customer.customer_id).customer.version == 1
    assert flow.events[record.customer.customer_id] == (event, older_event)

    update_headers = mutation_headers(1)
    updated = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=update_headers,
        json={"memo": None},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["memo"] is None
    assert updated.json()["data"]["audit_history"] == []
    assert updated.json()["data"]["audit_history_available"] is False
    assert updated.headers["etag"] == '"2"'

    assert (
        client.patch(
            f"/api/v1/customers/{record.customer.customer_id}",
            headers=mutation_headers(2),
            json={"deactivate": 1, "deactivation_reason": "Malformed lifecycle flag"},
        ).status_code
        == 422
    )

    deactivation_headers = mutation_headers(2)
    deactivated = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=deactivation_headers,
        json={"deactivate": True, "deactivation_reason": "Duplicate entered distinctly"},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["active"] is False
    assert deactivated.json()["data"]["can_manage"] is True
    assert deactivated.json()["data"]["can_deactivate"] is False
    assert deactivated.json()["data"]["audit_history"] == []
    assert deactivated.json()["data"]["audit_history_available"] is False
    assert deactivated.json()["data"]["customer_id"] == str(record.customer.customer_id)
    replayed_update = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=update_headers,
        json={"memo": "   "},
    )
    assert replayed_update.status_code == 200
    assert replayed_update.json()["data"]["version"] == 2
    assert replayed_update.json()["data"]["active"] is True
    replayed_deactivation = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=deactivation_headers,
        json={
            "deactivate": True,
            "deactivation_reason": "  Duplicate entered distinctly  ",
        },
    )
    assert replayed_deactivation.status_code == 200
    assert replayed_deactivation.json()["data"]["version"] == 3
    assert replayed_deactivation.json()["data"]["active"] is False
    repeated = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(3),
        json={"deactivate": True, "deactivation_reason": "Repeated command"},
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["current_version"] == 3
    inactive_update = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(3),
        json={"memo": "must remain read-only"},
    )
    assert inactive_update.status_code == 409
    assert inactive_update.json()["error"]["current_version"] == 3
    assert client.delete(f"/api/v1/customers/{record.customer.customer_id}").status_code == 405


def test_committed_customer_mutation_remains_successful_when_history_read_is_unavailable() -> None:
    @dataclass(slots=True)
    class HistoryUnavailableFlow(InMemoryCustomerFlow):
        def history(
            self,
            customer_id: UUID,
            *,
            property_id: UUID,
            limit: int,
            cursor: str | None,
        ) -> CustomerHistoryPage:
            del customer_id, property_id, limit, cursor
            raise CustomerResourceUnavailable

    property_id = uuid4()
    record = sample_record(property_id)
    flow = HistoryUnavailableFlow(property_id, {record.customer.customer_id: record})
    client = TestClient(
        create_app(
            actor_resolver=lambda _: manager(property_id, audit=True),
            customer_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(record.customer.version),
        json={"memo": "Committed even if history is temporarily unavailable"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["version"] == record.customer.version + 1
    assert response.json()["data"]["audit_history"] == []
    assert response.json()["data"]["audit_history_available"] is False


def test_normalized_noop_still_detects_a_concurrent_version_change() -> None:
    @dataclass(slots=True)
    class ConcurrentUpdateFlow(InMemoryCustomerFlow):
        def update(
            self,
            customer_id: UUID,
            *,
            legal_name: str,
            phone_number: str | None,
            email_address: str | None,
            contact_address: str | None,
            memo: str | None,
            confirmed_distinct: bool,
            expected_version: int,
            actor_id: str,
            idempotency_key: UUID,
            request_digest: str,
            id_document_number: str | None = None,
        ) -> CustomerRecord:
            current = self.get(customer_id)
            self.customers[customer_id] = replace(
                current,
                customer=replace(current.customer, version=current.customer.version + 1),
            )
            return InMemoryCustomerFlow.update(
                self,
                customer_id,
                legal_name=legal_name,
                phone_number=phone_number,
                email_address=email_address,
                contact_address=contact_address,
                memo=memo,
                confirmed_distinct=confirmed_distinct,
                expected_version=expected_version,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                id_document_number=id_document_number,
            )

    property_id = uuid4()
    record = sample_record(property_id)
    flow = ConcurrentUpdateFlow(property_id, {record.customer.customer_id: record})
    client = TestClient(
        create_app(
            actor_resolver=lambda _: manager(property_id),
            customer_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/api/v1/customers/{record.customer.customer_id}",
        headers=mutation_headers(record.customer.version),
        json={"legal_name": f"  {record.customer.legal_name}  "},
    )

    assert response.status_code == 412
    assert response.json()["error"]["current_version"] == 2


def test_postgres_flow_reports_new_version_before_inactive_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    current = sample_record(property_id)
    deactivated = replace(
        current,
        customer=replace(current.customer, version=current.customer.version + 1),
        deactivated_at=datetime(2026, 8, 24, tzinfo=UTC),
        deactivation_reason="Concurrent deactivation",
    )
    flow = PostgresCustomerResourceFlow("postgresql://unused")
    monkeypatch.setattr(flow, "get", lambda _: deactivated)
    monkeypatch.setattr(
        flow,
        "command_status",
        lambda **_: CustomerCommandStatus(False, None),
    )

    with pytest.raises(CustomerVersionConflict) as raised:
        flow.update(
            current.customer.customer_id,
            legal_name=current.customer.legal_name,
            phone_number=current.customer.phone_number,
            email_address=current.customer.email_address,
            contact_address=current.customer.contact_address,
            memo=current.customer.memo,
            confirmed_distinct=False,
            expected_version=current.customer.version,
            actor_id=str(uuid4()),
            idempotency_key=uuid4(),
            request_digest="a" * 64,
        )

    assert raised.value.current_version == deactivated.customer.version

    with pytest.raises(CustomerLifecycleConflict) as inactive:
        flow.update(
            current.customer.customer_id,
            legal_name=current.customer.legal_name,
            phone_number=current.customer.phone_number,
            email_address=current.customer.email_address,
            contact_address=current.customer.contact_address,
            memo="must remain read-only",
            confirmed_distinct=False,
            expected_version=deactivated.customer.version,
            actor_id=str(uuid4()),
            idempotency_key=uuid4(),
            request_digest="b" * 64,
        )

    assert inactive.value.current_version == deactivated.customer.version


def test_postgres_list_uses_immutable_cursor_and_literal_search_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    first_id = UUID("10000000-0000-0000-0000-000000000000")
    second_id = UUID("20000000-0000-0000-0000-000000000000")
    rows: list[tuple[object, ...]] = [
        (first_id, "Zulu", None, None, None, None, 1, None, None, property_id),
        (second_id, "Alpha", None, None, None, None, 1, None, None, property_id),
    ]
    queries: list[tuple[str, tuple[object, ...]]] = []
    timeouts: list[tuple[object, ...]] = []

    class Result:
        def __init__(self, values: list[tuple[object, ...]]) -> None:
            self.values = values

        def fetchone(self) -> tuple[object, ...] | None:
            return None if not self.values else self.values[0]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.values

    class ListConnection:
        def __enter__(self) -> "ListConnection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(
            self,
            statement: str,
            parameters: tuple[object, ...],
        ) -> Result:
            normalized = " ".join(statement.split())
            if "set_config('lock_timeout'" in normalized:
                timeouts.append(parameters)
                return Result([("1000",)])
            if "set_config('statement_timeout'" in normalized:
                timeouts.append(parameters)
                return Result([("3000",)])
            if "FROM app.customers" in normalized:
                queries.append((normalized, parameters))
                return Result(rows)
            if normalized.startswith("SELECT 1 FROM app.properties"):
                return Result([(1,)])
            raise AssertionError(normalized)

    connection_options: list[dict[str, object]] = []

    def connect(_: str, **options: object) -> ListConnection:
        connection_options.append(options)
        return ListConnection()

    monkeypatch.setattr(psycopg, "connect", connect)
    flow = PostgresCustomerResourceFlow("postgresql://list")

    first_page = flow.list(
        property_id,
        query=r"person_%\path",
        active=True,
        limit=1,
        cursor=None,
    )
    assert first_page.next_cursor is not None
    flow.list(
        property_id,
        query=r"person_%\path",
        active=True,
        limit=1,
        cursor=first_page.next_cursor,
    )

    assert "ORDER BY customer.id LIMIT %s" in queries[0][0]
    assert "left(customer.legal_name, 255)" in queries[0][0]
    assert "customer.phone_number" not in queries[0][0].split(" FROM ", 1)[0]
    assert "customer.email_address" not in queries[0][0].split(" FROM ", 1)[0]
    assert "customer.contact_address" not in queries[0][0].split(" FROM ", 1)[0]
    assert "customer.memo" not in queries[0][0].split(" FROM ", 1)[0]
    assert len(first_page.items[0].customer.legal_name.encode("utf-8")) <= 1020
    assert "customer.legal_name, customer.id" not in queries[0][0]
    assert queries[0][0].count("ESCAPE E'\\\\'") == 3
    assert "left(lower(customer.legal_name), 255) LIKE lower(%s)" in queries[0][0]
    assert "left(lower(%s)" not in queries[0][0]
    assert "ILIKE" not in queries[0][0]
    literal_pattern = r"person\_\%\\path%"
    assert queries[0][1] == (
        property_id,
        literal_pattern,
        literal_pattern,
        literal_pattern,
        2,
    )
    assert "customer.id > %s" in queries[1][0]
    assert queries[1][1][-2:] == (first_id, 2)
    assert timeouts == [("1000",), ("3000",), ("1000",), ("3000",)]

    flow.list(property_id, query="Straße", active=None, limit=1, cursor=None)
    assert queries[2][1][1:3] == ("Straße%", "Straße%")
    assert timeouts == [
        ("1000",),
        ("3000",),
        ("1000",),
        ("3000",),
        ("1000",),
        ("3000",),
    ]
    assert connection_options == [{"connect_timeout": 3}] * 3

    flow.list(property_id, query="%" * 255, active=None, limit=1, cursor=None)
    escaped_percent_pattern = (r"\%" * 255) + "%"
    assert queries[3][1][1:4] == (
        escaped_percent_pattern,
        escaped_percent_pattern,
        escaped_percent_pattern,
    )
    assert all(not str(pattern).endswith("\\") for pattern in queries[3][1][1:4])


def test_postgres_update_returns_a_concurrently_committed_idempotent_result() -> None:
    property_id = uuid4()
    customer_id = uuid4()
    actor_id = str(uuid4())
    original = CustomerRecord(Customer(customer_id, "Original Customer"), property_id)
    committed = CustomerRecord(
        Customer(customer_id, "Updated Customer", version=2),
        property_id,
    )

    class ConcurrentReplayFlow(PostgresCustomerResourceFlow):
        def __init__(self) -> None:
            super().__init__("postgresql://unused")
            self.get_calls = 0
            self.command_calls = 0

        def get(self, exact_customer_id: UUID) -> CustomerRecord:
            assert exact_customer_id == customer_id
            self.get_calls += 1
            return original if self.get_calls == 1 else committed

        def command_status(
            self,
            *,
            property_id: UUID,
            customer_id: UUID,
            action: str,
            idempotency_key: UUID,
            actor_id: str,
            request_digest: str | None = None,
        ) -> CustomerCommandStatus:
            del idempotency_key
            assert property_id == original.property_id
            assert customer_id == original.customer.customer_id
            assert action == "update"
            assert actor_id == actor_id_value
            assert request_digest == "a" * 64
            self.command_calls += 1
            return (
                CustomerCommandStatus(False, None)
                if self.command_calls == 1
                else CustomerCommandStatus(True, committed)
            )

    actor_id_value = actor_id
    flow = ConcurrentReplayFlow()

    result = flow.update(
        customer_id,
        legal_name="Updated Customer",
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        expected_version=1,
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="a" * 64,
    )

    assert result == committed
    assert flow.get_calls == 2
    assert flow.command_calls == 2


def test_postgres_detail_reads_customer_and_history_from_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    customer_id = uuid4()
    event_id = uuid4()
    actor_id = uuid4()
    statements: list[str] = []
    connections = 0

    class Result:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        def fetchone(self) -> tuple[object, ...] | None:
            return None if not self.rows else self.rows[0]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    class SnapshotConnection:
        def __enter__(self) -> "SnapshotConnection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: object = None) -> Result:
            del parameters
            normalized = " ".join(statement.split())
            statements.append(normalized)
            if normalized.startswith("SET TRANSACTION") or "set_config(" in normalized:
                return Result([])
            if "FROM app.customers" in normalized:
                return Result(
                    [
                        (
                            customer_id,
                            "Snapshot Customer",
                            None,
                            None,
                            None,
                            None,
                            1,
                            None,
                            None,
                            property_id,
                        )
                    ]
                )
            if "FROM app.audit_events" in normalized:
                return Result(
                    [
                        (
                            event_id,
                            datetime(2026, 8, 24, tzinfo=UTC),
                            actor_id,
                            "customer.created",
                            "Snapshot creation",
                            None,
                            {"version": 1},
                            event_id,
                            "SUCCEEDED",
                        )
                    ]
                )
            raise AssertionError(normalized)

    def connect(_: str, **options: object) -> SnapshotConnection:
        nonlocal connections
        assert options == {"connect_timeout": 3}
        connections += 1
        return SnapshotConnection()

    monkeypatch.setattr(psycopg, "connect", connect)

    record, history = PostgresCustomerResourceFlow("postgresql://snapshot").detail(
        customer_id,
        limit=50,
        cursor=None,
    )

    assert connections == 1
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert record.customer.version == 1
    assert history.items[0].resulting_state == {"version": 1}


def test_postgres_financial_summary_reads_totals_and_page_from_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    customer_id = uuid4()
    deposit_id = uuid4()
    statements: list[str] = []

    class Result:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        def fetchone(self) -> tuple[object, ...] | None:
            return None if not self.rows else self.rows[0]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    class SnapshotConnection:
        def __enter__(self) -> "SnapshotConnection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: object = None) -> Result:
            del parameters
            normalized = " ".join(statement.split())
            statements.append(normalized)
            if normalized.startswith("SET TRANSACTION") or "set_config(" in normalized:
                return Result([])
            if normalized.startswith("SELECT count(*)"):
                return Result([(1, 20_000, 20_000, 20_000, 0)])
            if normalized.startswith("SELECT app.deposit_resource_snapshot"):
                return Result(
                    [
                        (
                            {
                                "deposit_id": str(deposit_id),
                                "deposit_type": "PET",
                                "reservation_id": None,
                                "lease_id": str(uuid4()),
                                "pet_approval_id": str(uuid4()),
                                "required_usd_cents": 20_000,
                                "received_usd_cents": 20_000,
                                "held_refundable_usd_cents": 20_000,
                                "outstanding_required_usd_cents": 0,
                            },
                            date(2026, 8, 26),
                            deposit_id,
                        )
                    ]
                )
            raise AssertionError(normalized)

    monkeypatch.setattr(
        PostgresCustomerResourceFlow,
        "get",
        lambda _self, _customer_id: sample_record(property_id),
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: SnapshotConnection())

    summary = PostgresCustomerResourceFlow("postgresql://snapshot").financial_summary(
        customer_id,
        deposit_limit=50,
        deposit_cursor=None,
    )

    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert statements.index(
        next(value for value in statements if value.startswith("SELECT count"))
    ) < (
        statements.index(
            next(
                value
                for value in statements
                if value.startswith("SELECT app.deposit_resource_snapshot")
            )
        )
    )
    assert summary["deposit_aggregate"] == {
        "count": 1,
        "required_usd_cents": 20_000,
        "received_usd_cents": 20_000,
        "held_refundable_usd_cents": 20_000,
        "outstanding_required_usd_cents": 0,
    }


def test_customer_history_cursor_requires_an_explicit_timezone() -> None:
    event_id = uuid4()
    naive_cursor = _encode_history_cursor(datetime(2026, 8, 24, 12, 30), event_id)

    with pytest.raises(CustomerResourceInvalid, match="history cursor is invalid"):
        _decode_history_cursor(naive_cursor)

    offset_cursor = _encode_history_cursor(
        datetime.fromisoformat("2026-08-24T12:30:00+07:00"), event_id
    )
    assert _decode_history_cursor(offset_cursor) == (
        datetime(2026, 8, 24, 5, 30, tzinfo=UTC),
        event_id,
    )


def test_customer_search_rate_guard_is_scoped_and_bounded() -> None:
    property_id = uuid4()
    other_property_id = uuid4()
    guard = SlidingWindowCustomerSearchRateGuard(
        maximum=2,
        window_seconds=1,
        clock=lambda: 100.0,
    )

    assert guard.allow(actor_id="actor-1", source="127.0.0.1", property_id=property_id)
    assert guard.allow(actor_id="actor-1", source="127.0.0.1", property_id=property_id)
    assert not guard.allow(actor_id="actor-1", source="127.0.0.1", property_id=property_id)
    assert guard.allow(actor_id="actor-2", source="127.0.0.1", property_id=property_id)
    assert guard.allow(actor_id="actor-1", source="127.0.0.1", property_id=other_property_id)


def test_customer_search_rate_guard_bounds_and_expires_identity_keys() -> None:
    now = 100.0
    guard = SlidingWindowCustomerSearchRateGuard(
        maximum=2,
        maximum_keys=2,
        window_seconds=1,
        clock=lambda: now,
    )
    first_property = uuid4()
    second_property = uuid4()
    third_property = uuid4()

    assert guard.allow(actor_id="actor-1", source="127.0.0.1", property_id=first_property)
    assert guard.allow(actor_id="actor-2", source="127.0.0.2", property_id=second_property)
    assert not guard.allow(actor_id="actor-3", source="127.0.0.3", property_id=third_property)

    now = 102.0
    assert guard.allow(actor_id="actor-3", source="127.0.0.3", property_id=third_property)


def test_customer_reads_require_exact_scope_and_audit_history_requires_audit_view() -> None:
    property_id = uuid4()
    other_property_id = uuid4()
    record = sample_record(property_id)
    event = CustomerHistoryEvent(
        event_id=uuid4(),
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        actor_id=uuid4(),
        action="customer.updated",
        reason="Authorized update",
        previous_state={"legal_name": "Dara"},
        resulting_state={"legal_name": "Dara Sok"},
        correlation_id=uuid4(),
        outcome="SUCCEEDED",
    )
    flow = InMemoryCustomerFlow(
        property_id,
        {record.customer.customer_id: record},
        {record.customer.customer_id: (event,)},
    )
    wrong_scope = TestClient(
        create_app(
            actor_resolver=lambda _: reader(other_property_id),
            customer_resource_flow=flow,
        )
    )
    property_manager = TestClient(
        create_app(
            actor_resolver=lambda _: AuthenticatedActor(
                actor_id=str(uuid4()),
                capability_grants=frozenset(
                    {
                        CapabilityGrant(
                            capability="property.manage",
                            property_ids=frozenset({str(property_id)}),
                        )
                    }
                ),
            ),
            customer_resource_flow=flow,
        )
    )
    scoped_reader = TestClient(
        create_app(
            actor_resolver=lambda _: reader(property_id),
            customer_resource_flow=flow,
        )
    )

    concealed = wrong_scope.get(f"/api/v1/customers/{record.customer.customer_id}")
    assert concealed.status_code == 404
    assert concealed.headers["cache-control"] == "private, no-store"
    assert concealed.headers["vary"] == "Cookie"
    assert flow.detail_calls == 0
    assert wrong_scope.get(f"/api/v1/customers/{uuid4()}").status_code == 404
    assert (
        wrong_scope.get(
            f"/api/v1/customers/{record.customer.customer_id}/financial-summary"
        ).status_code
        == 404
    )
    assert (
        wrong_scope.patch(
            f"/api/v1/customers/{record.customer.customer_id}",
            headers=mutation_headers(record.customer.version),
            json={"memo": "probe"},
        ).status_code
        == 404
    )
    assert property_manager.get(f"/api/v1/properties/{property_id}/customers").status_code == 403
    detail = scoped_reader.get(f"/api/v1/customers/{record.customer.customer_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["audit_history"] == []
    assert detail.json()["data"]["can_view_audit"] is False
    assert flow.detail_calls == 0


def test_customer_financial_summary_is_truthful_and_exposes_no_export_or_ledger_route() -> None:
    property_id = uuid4()
    record = sample_record(property_id)
    flow = InMemoryCustomerFlow(property_id, {record.customer.customer_id: record})
    client = TestClient(
        create_app(
            actor_resolver=lambda _: reader(property_id),
            customer_resource_flow=flow,
        )
    )

    response = client.get(f"/api/v1/customers/{record.customer.customer_id}/financial-summary")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "source_status": "UNAVAILABLE_UNTIL_FINANCIAL_SOURCES_ARE_IMPLEMENTED",
        "source_availability": {
            "deposits": "UNAVAILABLE_NOT_IMPLEMENTED",
            "invoices": "UNAVAILABLE_NOT_IMPLEMENTED",
            "late_charges": "UNAVAILABLE_NOT_IMPLEMENTED",
            "payments": "UNAVAILABLE_NOT_IMPLEMENTED",
            "customer_credit": "UNAVAILABLE_NOT_IMPLEMENTED",
        },
        "currency_summaries": [],
        "deposit_liabilities": [],
        "deposit_liabilities_page": {"next_cursor": None, "limit": 50},
        "deposit_aggregate": {
            "count": 0,
            "required_usd_cents": 0,
            "received_usd_cents": 0,
            "held_refundable_usd_cents": 0,
            "outstanding_required_usd_cents": 0,
        },
        "customer_credit_is_separate_from_deposit": True,
    }
    assert (
        client.get(
            f"/api/v1/customers/{record.customer.customer_id}/financial-summary?currency=USD"
        ).status_code
        == 400
    )
    # The separate ledger now exists, but Customer read never grants ledger access.
    assert (
        client.get(f"/api/v1/customers/{record.customer.customer_id}/account-ledger").status_code
        == 403
    )
    assert client.get(f"/api/v1/customers/{record.customer.customer_id}/export").status_code == 404


def test_customer_id_number_is_required_unique_shown_in_detail_and_never_cleared() -> None:
    """DL-071 answer 11 and the owner's 2026-10-21 answer (V1-059 part B)."""
    property_id = uuid4()
    existing = sample_record(property_id)
    existing = replace(existing, customer=replace(existing.customer, id_document_number="N0123456"))
    flow = InMemoryCustomerFlow(property_id, {existing.customer.customer_id: existing})
    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), customer_resource_flow=flow)
    )
    url = f"/api/v1/properties/{property_id}/customers"
    missing = client.post(
        url,
        json={"customer_id": str(uuid4()), "legal_name": "Srey Mom"},
        headers=mutation_headers(),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["fields"] == ["body.id_document_number"]
    for blank in ("   ", "- -"):
        assert (
            client.post(
                url,
                json={
                    "customer_id": str(uuid4()),
                    "legal_name": "Srey",
                    "id_document_number": blank,
                },
                headers=mutation_headers(),
            ).status_code
            == 422
        )
    duplicate = client.post(
        url,
        json={
            "customer_id": str(uuid4()),
            "legal_name": "Dara S.",
            "id_document_number": "n 0123-456",
            "confirmed_distinct": True,
        },
        headers=mutation_headers(),
    )
    assert duplicate.status_code == 409
    error = duplicate.json()["error"]
    assert error["code"] == "CUSTOMER_ID_NUMBER_IN_USE"
    assert error["fields"] == ["id_document_number"]
    assert error["existing_customer"] == {
        "customer_id": str(existing.customer.customer_id),
        "legal_name": "Dara Sok",
    }
    assert "0123" not in duplicate.text
    created = client.post(
        url,
        json={"customer_id": str(uuid4()), "legal_name": "Srey Mom", "id_document_number": " P77 "},
        headers=mutation_headers(),
    )
    assert created.status_code == 201
    assert created.json()["data"]["id_document_number"] == "P77"
    listed = client.get(url)
    assert "N0123456" not in listed.text and "P77" not in listed.text
    customer_id = created.json()["data"]["customer_id"]
    cleared = client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"id_document_number": None},
        headers=mutation_headers(1),
    )
    assert cleared.status_code == 422
    corrected = client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"id_document_number": "P78"},
        headers=mutation_headers(1),
    )
    assert corrected.status_code == 200
    assert corrected.json()["data"]["id_document_number"] == "P78"
