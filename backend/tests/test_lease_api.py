"""API-035 through API-038 Lease and coordinated move-in HTTP contracts."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease import (
    LeaseAddSignerCommand,
    LeaseCancelCommand,
    LeaseDraftCommand,
    LeaseRecordSignatureCommand,
    LeaseSignCommand,
    LeaseStatus,
    LeaseTerminateCommand,
    LeaseUpdateDraftCommand,
)
from property_rental.lease_api import (
    NO_RESTRICTED_EVENTS,
    LeasePage,
    LeaseResource,
    LeaseResourceNotFound,
    LeaseSignerResource,
    LeaseTimelineEvent,
    LeaseTimelinePage,
    LeaseTimelineVisibility,
)
from property_rental.move_in import (
    AddLeaseOccupantCommand,
    CompleteMoveInCommand,
    MoveInSnapshot,
    RecordLeaseMoveInCommand,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def resource(
    property_id: UUID, *, lease_status: LeaseStatus = LeaseStatus.DRAFTED
) -> LeaseResource:
    return LeaseResource(
        lease_id=uuid4(),
        property_id=property_id,
        unit_id=uuid4(),
        unit_number="101",
        primary_tenant_id=uuid4(),
        primary_tenant_name="Primary Tenant",
        status=lease_status,
        start_date=date(2026, 9, 1),
        end_date=date(2027, 8, 31),
        monthly_rent_usd_cents=80_000,
        predecessor_lease_id=None,
        signed_at=None,
        terminated_at=None,
        actual_termination_date=None,
        version=1,
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
        pet_deposit_required=False,
        pet_description=None,
    )


@dataclass(slots=True)
class InMemoryLeaseFlow:
    resources: dict[UUID, LeaseResource] = field(default_factory=dict)
    draft_command: LeaseDraftCommand | None = None
    update_command: LeaseUpdateDraftCommand | None = None
    signer_command: LeaseAddSignerCommand | None = None
    signature_command: LeaseRecordSignatureCommand | None = None
    sign_command: LeaseSignCommand | None = None
    terminate_command: LeaseTerminateCommand | None = None
    move_in_command: CompleteMoveInCommand | None = None
    cancel_command: LeaseCancelCommand | None = None
    record_move_in_command: RecordLeaseMoveInCommand | None = None
    occupant_command: AddLeaseOccupantCommand | None = None
    visibilities: list[LeaseTimelineVisibility] = field(default_factory=list)

    def list(
        self,
        property_id: UUID,
        *,
        lease_status: LeaseStatus | None,
        unit_id: UUID | None,
        customer_id: UUID | None,
        starts_on_or_after: date | None,
        ends_on_or_before: date | None,
        period: str | None,
        as_of: date | None,
        approaching_days: int,
        limit: int,
        cursor: str | None,
    ) -> LeasePage:
        del starts_on_or_after, ends_on_or_before, period, as_of, approaching_days, cursor
        values = tuple(
            value
            for value in self.resources.values()
            if value.property_id == property_id
            and (lease_status is None or value.status is lease_status)
            and (unit_id is None or value.unit_id == unit_id)
            and (customer_id is None or value.primary_tenant_id == customer_id)
        )
        return LeasePage(values[:limit], None)

    def get(
        self, lease_id: UUID, *, visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS
    ) -> LeaseResource:
        self.visibilities.append(visibility)
        try:
            return self.resources[lease_id]
        except KeyError as exc:
            raise LeaseResourceNotFound from exc

    def timeline(
        self,
        lease_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        visibility: LeaseTimelineVisibility = NO_RESTRICTED_EVENTS,
    ) -> LeaseTimelinePage:
        values = self.get(lease_id, visibility=visibility).timeline
        start = 0 if cursor is None else 1
        items = values[start : start + limit]
        next_cursor = "next" if start + limit < len(values) else None
        return LeaseTimelinePage(items, next_cursor)

    def draft(
        self,
        property_id: UUID,
        command: LeaseDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del actor
        self.draft_command = command
        value = LeaseResource(
            command.lease_id,
            property_id,
            command.unit_id,
            "101",
            command.primary_tenant_id,
            "Primary Tenant",
            LeaseStatus.DRAFTED,
            command.start_date,
            command.end_date,
            command.monthly_rent_usd_cents,
            command.predecessor_lease_id,
            None,
            None,
            None,
            1,
            datetime(2026, 8, 26, tzinfo=UTC),
            False,
            None,
            security_deposit_id=command.security_deposit_id,
            planned_occupant_customer_ids=command.planned_occupant_customer_ids,
        )
        self.resources[value.lease_id] = value
        return value

    def update_draft(
        self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del actor
        self.update_command = command
        current = self.get(command.lease_id)
        value = replace(
            current,
            start_date=command.start_date,
            end_date=command.end_date,
            monthly_rent_usd_cents=command.monthly_rent_usd_cents,
            version=current.version + 1,
        )
        self.resources[value.lease_id] = value
        return value

    def add_signer(
        self, command: LeaseAddSignerCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del actor
        self.signer_command = command
        current = self.get(command.lease_id)
        value = replace(
            current,
            version=current.version + 1,
            signers=(
                *current.signers,
                LeaseSignerResource(
                    command.signer_id,
                    command.customer_id,
                    "Joint Signer",
                    False,
                    None,
                    datetime(2026, 8, 26, tzinfo=UTC),
                ),
            ),
        )
        self.resources[value.lease_id] = value
        return value

    def record_signature(
        self, command: LeaseRecordSignatureCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del actor
        self.signature_command = command
        current = self.get(command.lease_id)
        value = replace(current, version=current.version + 1)
        self.resources[value.lease_id] = value
        return value

    def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        del actor
        self.sign_command = command
        current = self.get(command.lease_id)
        value = replace(
            current,
            status=LeaseStatus.SIGNED,
            signed_at=command.signed_at,
            version=current.version + 1,
        )
        self.resources[value.lease_id] = value
        return value

    def terminate(
        self, command: LeaseTerminateCommand, *, actor: AuthenticatedActor
    ) -> LeaseResource:
        del actor
        self.terminate_command = command
        current = self.get(command.lease_id)
        value = replace(
            current,
            status=LeaseStatus.TERMINATED,
            actual_termination_date=command.actual_termination_date,
            terminated_at=command.occurred_at,
            version=current.version + 1,
        )
        self.resources[value.lease_id] = value
        return value

    def complete_move_in(
        self,
        property_id: UUID,
        command: CompleteMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> MoveInSnapshot:
        del actor
        self.move_in_command = command
        current = self.get(command.lease_id)
        return MoveInSnapshot(
            command.event_id,
            property_id,
            command.reservation_id,
            command.expected_reservation_version + 1,
            command.lease_id,
            command.expected_lease_version + 1,
            current.unit_id,
            command.expected_unit_version + 1,
            uuid4(),
            2,
            command.actual_move_in_date,
            tuple(value.occupancy_id for value in command.occupants),
        )

    def cancel(self, command: LeaseCancelCommand, *, actor: AuthenticatedActor) -> LeaseResource:
        del actor
        self.cancel_command = command
        current = self.get(command.lease_id)
        value = replace(current, status=LeaseStatus.CANCELLED, version=current.version + 1)
        self.resources[value.lease_id] = value
        return value

    def record_move_in(
        self,
        property_id: UUID,
        command: RecordLeaseMoveInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, actor
        self.record_move_in_command = command
        current = self.get(command.lease_id)
        value = replace(current, version=current.version + 1)
        self.resources[value.lease_id] = value
        return value

    def add_occupant(
        self,
        property_id: UUID,
        command: AddLeaseOccupantCommand,
        *,
        actor: AuthenticatedActor,
    ) -> LeaseResource:
        del property_id, actor
        self.occupant_command = command
        current = self.get(command.lease_id)
        value = replace(current, version=current.version + 1)
        self.resources[value.lease_id] = value
        return value


def headers(*, version: int | None = None) -> dict[str, str]:
    result = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    if version is not None:
        result["If-Match"] = f'"{version}"'
    return result


def client(flow: InMemoryLeaseFlow, authenticated: AuthenticatedActor) -> TestClient:
    value = TestClient(create_app(actor_resolver=lambda _: authenticated, lease_resource_flow=flow))
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def test_list_is_bounded_private_filtered_and_scope_sensitive() -> None:
    property_id = uuid4()
    drafted = resource(property_id)
    signed = resource(property_id, lease_status=LeaseStatus.SIGNED)
    flow = InMemoryLeaseFlow({drafted.lease_id: drafted, signed.lease_id: signed})
    response = client(flow, actor(property_id, "leases.read", "leases.draft")).get(
        f"/api/v1/properties/{property_id}/leases?status=DRAFTED&limit=1"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["can_create"] is True
    assert response.json()["page"] == {"next_cursor": None, "limit": 1}
    assert [item["status"] for item in response.json()["data"]] == ["DRAFTED"]
    assert (
        client(flow, actor(property_id, "leases.read"))
        .get(f"/api/v1/properties/{property_id}/leases?unknown=true")
        .status_code
        == 400
    )
    denied = client(flow, actor(uuid4(), "leases.read")).get(f"/api/v1/leases/{drafted.lease_id}")
    assert denied.status_code == 404


def test_create_and_update_require_csrf_idempotency_and_optimistic_version() -> None:
    property_id = uuid4()
    authenticated = actor(property_id, "leases.read", "leases.draft")
    flow = InMemoryLeaseFlow()
    lease_id = uuid4()
    additional_customer_id = uuid4()
    planned_customer_id = uuid4()
    service_id = uuid4()
    approval_id = uuid4()
    deposit_id = uuid4()
    payload = {
        "lease_id": str(lease_id),
        "unit_id": str(uuid4()),
        "primary_tenant_id": str(uuid4()),
        "primary_signer_id": str(uuid4()),
        "start_date": "2026-09-01",
        "end_date": "2027-08-31",
        "monthly_rent_usd_cents": 80000,
        "predecessor_lease_id": None,
        "additional_signers": [
            {"signer_id": str(uuid4()), "customer_id": str(additional_customer_id)}
        ],
        "planned_occupant_customer_ids": [str(planned_customer_id)],
        "service_terms": [
            {
                "term_id": str(uuid4()),
                "property_service_id": str(service_id),
                "applicable_from": "2026-09-01",
                "applicable_through": "2027-08-31",
                "service_approval_period_id": str(approval_id),
                "terms_reference": "owner-approved-parking",
            }
        ],
        "pet_term": {
            "approval_id": str(uuid4()),
            "approved_date": "2026-09-01",
            "deposit_required_by_signed_terms": True,
            "pet_description": "One approved indoor cat",
        },
        "security_deposit_id": str(deposit_id),
        "event_id": str(uuid4()),
        "reason": "Approved source Lease terms",
    }
    api = client(flow, authenticated)
    rejected = api.post(
        f"/api/v1/properties/{property_id}/leases",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    created = api.post(f"/api/v1/properties/{property_id}/leases", json=payload, headers=headers())
    missing_version = api.patch(
        f"/api/v1/leases/{lease_id}",
        json={
            "event_id": str(uuid4()),
            "start_date": "2026-09-01",
            "end_date": "2027-08-31",
            "monthly_rent_usd_cents": 85000,
            "reason": "Approved Rent correction",
        },
        headers=headers(),
    )
    updated = api.patch(
        f"/api/v1/leases/{lease_id}",
        json={
            "event_id": str(uuid4()),
            "start_date": "2026-09-01",
            "end_date": "2027-08-31",
            "monthly_rent_usd_cents": 85000,
            "reason": "Approved Rent correction",
        },
        headers=headers(version=1),
    )
    partial = api.patch(
        f"/api/v1/leases/{lease_id}",
        json={
            "event_id": str(uuid4()),
            "monthly_rent_usd_cents": 90000,
            "reason": "Rent-only correction preserves contractual dates",
        },
        headers=headers(version=2),
    )

    assert rejected.status_code == 403
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    assert created.headers["location"] == f"/api/v1/leases/{lease_id}"
    assert created.json()["data"]["can_renew"] is False
    assert flow.draft_command is not None
    assert flow.draft_command.additional_signers[0].customer_id == additional_customer_id
    assert flow.draft_command.planned_occupant_customer_ids == (planned_customer_id,)
    assert flow.draft_command.service_terms[0].property_service_id == service_id
    assert flow.draft_command.pet_term is not None
    assert flow.draft_command.pet_term.deposit_required_by_signed_terms is True
    assert flow.draft_command.security_deposit_id == deposit_id
    assert missing_version.status_code == 428
    assert updated.status_code == 200
    assert updated.json()["data"]["monthly_rent_usd_cents"] == 85000
    assert partial.status_code == 200
    assert partial.json()["data"]["start_date"] == "2026-09-01"
    assert partial.json()["data"]["end_date"] == "2027-08-31"
    assert partial.json()["data"]["monthly_rent_usd_cents"] == 90000


def test_signer_signing_renewal_and_termination_are_explicit_commands() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryLeaseFlow({current.lease_id: current})
    authenticated = actor(
        property_id,
        "leases.read",
        "leases.draft",
        "lease_signers.manage",
        "leases.sign",
        "leases.terminate",
    )
    api = client(flow, authenticated)
    added = api.post(
        f"/api/v1/leases/{current.lease_id}/signers",
        headers=headers(version=1),
        json={
            "signer_id": str(uuid4()),
            "customer_id": str(uuid4()),
            "event_id": str(uuid4()),
            "reason": "Joint responsibility recorded",
        },
    )
    signed = api.post(
        f"/api/v1/leases/{current.lease_id}/sign",
        headers=headers(version=2),
        json={
            "event_id": str(uuid4()),
            "reason": "All required Signers completed",
        },
    )
    successor_id = uuid4()
    renewed = api.post(
        f"/api/v1/leases/{current.lease_id}/renew",
        headers=headers(),
        json={
            "lease_id": str(successor_id),
            "primary_signer_id": str(uuid4()),
            "event_id": str(uuid4()),
            "start_date": "2027-09-01",
            "end_date": "2028-08-31",
            "monthly_rent_usd_cents": 90000,
            "reason": "Approved successor Lease",
        },
    )
    terminated = api.post(
        f"/api/v1/leases/{current.lease_id}/terminate",
        headers=headers(version=3),
        json={
            "event_id": str(uuid4()),
            "actual_termination_date": "2027-08-15",
            "governing_event_reference": "approved-termination-1",
            "reason": "Authorized termination boundary",
        },
    )

    assert added.status_code == 201
    assert added.headers["location"].startswith("/api/v1/lease-signers/")
    assert signed.json()["data"]["status"] == "SIGNED"
    assert signed.json()["data"]["can_renew"] is True
    assert renewed.status_code == 201
    assert renewed.headers["location"] == f"/api/v1/leases/{successor_id}"
    assert renewed.json()["data"]["predecessor_lease_id"] == str(current.lease_id)
    assert terminated.json()["data"]["status"] == "TERMINATED"


def test_signing_routes_take_no_signing_time_from_the_request() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryLeaseFlow({current.lease_id: current})
    api = client(flow, actor(property_id, "leases.read", "leases.sign"))
    signer_id = uuid4()
    signature_path = f"/api/v1/lease-signers/{signer_id}?lease_id={current.lease_id}"
    sign_path = f"/api/v1/leases/{current.lease_id}/sign"
    device_time = "2026-08-27T01:00:00Z"

    refused_signature = api.patch(
        signature_path,
        headers=headers(version=1),
        json={"event_id": str(uuid4()), "signed_at": device_time, "reason": "Signer verified"},
    )
    refused_signing = api.post(
        sign_path,
        headers=headers(version=1),
        json={"event_id": str(uuid4()), "signed_at": device_time, "reason": "Signers completed"},
    )

    assert refused_signature.status_code == 422
    assert refused_signing.status_code == 422
    assert refused_signature.json()["error"]["fields"] == ["body.signed_at"]
    assert refused_signing.json()["error"]["fields"] == ["body.signed_at"]
    assert (flow.signature_command, flow.sign_command) == (None, None)

    recorded = api.patch(
        signature_path,
        headers=headers(version=1),
        json={"event_id": str(uuid4()), "reason": "Signer verified"},
    )
    signed = api.post(
        sign_path,
        headers=headers(version=2),
        json={"event_id": str(uuid4()), "reason": "Signers completed"},
    )

    assert recorded.status_code == 200, recorded.text
    assert signed.status_code == 200, signed.text
    assert flow.signature_command is not None
    assert flow.signature_command.signer_id == signer_id
    assert flow.signature_command.signed_at is None
    assert flow.sign_command is not None
    assert flow.sign_command.signed_at is None


def test_terminate_route_takes_no_termination_time_from_the_request() -> None:
    """Owner answer (a) to Q-2026-10-14-112 point 1 (V1-056 sub-slice 10i-1): the termination
    route sends no time to the flow, so the database takes its own; a body that still sends one is
    refused (422) and the flow is not called."""
    property_id = uuid4()
    signed = replace(resource(property_id, lease_status=LeaseStatus.SIGNED), version=2)
    flow = InMemoryLeaseFlow({signed.lease_id: signed})
    api = client(flow, actor(property_id, "leases.read", "leases.terminate"))
    path = f"/api/v1/leases/{signed.lease_id}/terminate"
    body = {
        "event_id": str(uuid4()),
        "actual_termination_date": "2027-08-15",
        "governing_event_reference": "approved-termination-1",
        "reason": "Authorized termination boundary",
    }

    refused = api.post(
        path, headers=headers(version=2), json={**body, "occurred_at": "2027-08-15T01:00:00Z"}
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["fields"] == ["body.occurred_at"]
    assert [flow.terminate_command] == [None]

    terminated = api.post(path, headers=headers(version=2), json=body)

    assert terminated.status_code == 200, terminated.text
    assert flow.terminate_command is not None
    assert flow.terminate_command.occurred_at is None


def test_coordinated_occupancy_and_complete_move_in_share_atomic_service_boundary() -> None:
    property_id = uuid4()
    signed = resource(property_id, lease_status=LeaseStatus.SIGNED)
    signed = replace(signed, version=2)
    flow = InMemoryLeaseFlow({signed.lease_id: signed})
    api = client(flow, actor(property_id, "leases.read", "reservations.complete"))
    reservation_id = uuid4()
    occupant_id = uuid4()
    shared = {
        "event_id": str(uuid4()),
        "expected_lease_version": 2,
        "expected_unit_version": 3,
        "actual_move_in_date": "2026-09-01",
        "occupants": [{"occupancy_id": str(uuid4()), "customer_id": str(occupant_id)}],
        "reason": "All server-evaluated prerequisites passed",
    }
    occupancy = api.post(
        f"/api/v1/leases/{signed.lease_id}/occupancies",
        headers=headers(version=1),
        json={"reservation_id": str(reservation_id), **shared},
    )
    completed = api.post(
        f"/api/v1/reservations/{reservation_id}/complete-move-in",
        headers=headers(version=1),
        json={"lease_id": str(signed.lease_id), **shared, "event_id": str(uuid4())},
    )
    move_out = api.post(
        f"/api/v1/occupancies/{uuid4()}/end",
        headers={"Origin": "https://localhost", "X-CSRF-Token": "csrf"},
    )

    assert occupancy.status_code == 201
    assert occupancy.headers["location"] == (f"/api/v1/leases/{signed.lease_id}/occupancies")
    assert completed.status_code == 200
    assert completed.json()["data"]["reservation_version"] == 2
    assert flow.move_in_command is not None
    assert flow.move_in_command.authorization_reference == "reservations.complete"
    assert move_out.status_code == 409


def test_timeline_is_bounded_paginated_and_rejects_unknown_queries() -> None:
    property_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    current = replace(
        resource(property_id),
        timeline=(
            LeaseTimelineEvent(
                first_id,
                "lease.draft",
                datetime(2026, 8, 26, tzinfo=UTC),
                "Drafted",
                uuid4(),
                str(first_id),
                f"/api/v1/leases/source#timeline-{first_id}",
            ),
            LeaseTimelineEvent(
                second_id,
                "lease.draft.update",
                datetime(2026, 8, 26, tzinfo=UTC) + timedelta(seconds=1),
                "Corrected",
                uuid4(),
                str(second_id),
                f"/api/v1/leases/source#timeline-{second_id}",
            ),
        ),
    )
    api = client(InMemoryLeaseFlow({current.lease_id: current}), actor(property_id, "leases.read"))
    first = api.get(f"/api/v1/leases/{current.lease_id}/timeline?limit=1")
    second = api.get(
        f"/api/v1/leases/{current.lease_id}/timeline?limit=1&cursor="
        f"{first.json()['page']['next_cursor']}"
    )
    unknown = api.get(f"/api/v1/leases/{current.lease_id}/timeline?unknown=true")

    assert first.status_code == 200
    assert first.json()["data"][0]["event_id"] == str(first_id)
    assert first.json()["page"]["next_cursor"] == "next"
    assert second.json()["data"][0]["event_id"] == str(second_id)
    assert second.json()["page"]["next_cursor"] is None
    assert unknown.status_code == 400


def test_timeline_restricted_visibility_follows_only_the_actor_read_grants() -> None:
    property_id = uuid4()
    other_property = uuid4()
    current = resource(property_id)
    lease_only = actor(property_id, "leases.read")
    flow = InMemoryLeaseFlow({current.lease_id: current})
    api = client(flow, lease_only)
    assert api.get(f"/api/v1/leases/{current.lease_id}").status_code == 200
    assert api.get(f"/api/v1/leases/{current.lease_id}/timeline").status_code == 200
    assert flow.visibilities and all(
        value == NO_RESTRICTED_EVENTS and not value.restricted for value in flow.visibilities
    )

    reader = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {
                CapabilityGrant("leases.read", frozenset({str(property_id)})),
                CapabilityGrant("invoices.read", frozenset({str(property_id)})),
                CapabilityGrant(
                    "rent_nonpayment.read", frozenset({str(other_property), "not-a-uuid"})
                ),
            }
        ),
    )
    flow = InMemoryLeaseFlow({current.lease_id: current})
    api = client(flow, reader)
    assert api.get(f"/api/v1/leases/{current.lease_id}").status_code == 200
    assert api.get(f"/api/v1/leases/{current.lease_id}/timeline").status_code == 200
    expected = LeaseTimelineVisibility(UUID(reader.actor_id), (property_id,), (other_property,))
    assert flow.visibilities[0] == expected
    assert flow.visibilities[-1] == expected


def test_sign_route_forwards_the_reservation_the_signing_completes() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryLeaseFlow({current.lease_id: current})
    api = client(flow, actor(property_id, "leases.read", "leases.sign"))
    reservation_id = uuid4()

    signed = api.post(
        f"/api/v1/leases/{current.lease_id}/sign",
        headers=headers(version=1),
        json={
            "event_id": str(uuid4()),
            "reason": "Signers completed",
            "reservation_id": str(reservation_id),
        },
    )

    assert signed.status_code == 200, signed.text
    assert flow.sign_command is not None
    assert flow.sign_command.reservation_id == reservation_id


def test_cancel_draft_and_lease_move_in_routes_need_capability_and_version() -> None:
    property_id = uuid4()
    draft = resource(property_id)
    signed = replace(resource(property_id, lease_status=LeaseStatus.SIGNED), version=2)
    flow = InMemoryLeaseFlow({draft.lease_id: draft, signed.lease_id: signed})
    cancel_path = f"/api/v1/leases/{draft.lease_id}/cancel"
    move_in_path = f"/api/v1/leases/{signed.lease_id}/move-in"
    cancel_body = {"event_id": str(uuid4()), "reason": "Customer chose another Unit"}
    occupant_id = uuid4()
    occupancy_id = uuid4()
    move_in_body = {
        "event_id": str(uuid4()),
        "actual_move_in_date": "2026-09-01",
        "occupants": [{"occupancy_id": str(occupancy_id), "customer_id": str(occupant_id)}],
        "reason": "Keys handed over",
    }

    # Without the capability the Lease is hidden, as on the other Lease commands.
    reader = client(flow, actor(property_id, "leases.read"))
    assert reader.post(cancel_path, headers=headers(version=1), json=cancel_body).status_code == 404
    assert (
        reader.post(move_in_path, headers=headers(version=2), json=move_in_body).status_code == 404
    )
    assert (flow.cancel_command, flow.record_move_in_command) == (None, None)

    api = client(flow, actor(property_id, "leases.read", "leases.draft", "reservations.complete"))
    assert api.post(cancel_path, headers=headers(), json=cancel_body).status_code == 428
    assert api.post(move_in_path, headers=headers(), json=move_in_body).status_code == 428

    cancelled = api.post(cancel_path, headers=headers(version=1), json=cancel_body)
    moved_in = api.post(move_in_path, headers=headers(version=2), json=move_in_body)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.headers["etag"] == '"2"'
    assert flow.cancel_command is not None
    assert flow.cancel_command.expected_version == 1
    assert flow.cancel_command.reason == "Customer chose another Unit"
    assert flow.cancel_command.authorization_reference == "leases.draft"
    assert moved_in.status_code == 200, moved_in.text
    assert moved_in.headers["etag"] == '"3"'
    command = flow.record_move_in_command
    assert command is not None
    assert command.expected_lease_version == 2
    assert command.actual_move_in_date == date(2026, 9, 1)
    assert [(value.occupancy_id, value.customer_id) for value in command.occupants] == [
        (occupancy_id, occupant_id)
    ]
    assert command.authorization_reference == "reservations.complete"


def test_add_occupant_route_needs_the_move_in_capability_version_and_a_dated_occupancy() -> None:
    """V1-060 B6 (DL-102): Add occupant passes the person, and after the move-in their own
    Occupancy with its date; an Occupancy without a date is refused before the database."""
    property_id = uuid4()
    signed = replace(resource(property_id, lease_status=LeaseStatus.SIGNED), version=4)
    flow = InMemoryLeaseFlow({signed.lease_id: signed})
    path = f"/api/v1/leases/{signed.lease_id}/occupants"
    friend = uuid4()
    occupancy_id = uuid4()
    body = {
        "event_id": str(uuid4()),
        "customer_id": str(friend),
        "occupancy_id": str(occupancy_id),
        "move_in_date": "2026-10-20",
        "reason": "Sok Dara's friend moved in on 20/10/2026",
    }

    # Without the move-in capability the Lease is hidden, as on the other Lease commands.
    reader = client(flow, actor(property_id, "leases.read", "leases.draft"))
    assert reader.post(path, headers=headers(version=4), json=body).status_code == 404
    assert [flow.occupant_command] == [None]

    api = client(flow, actor(property_id, "leases.read", "reservations.complete"))
    assert api.post(path, headers=headers(), json=body).status_code == 428
    undated = {key: value for key, value in body.items() if key != "move_in_date"}
    assert api.post(path, headers=headers(version=4), json=undated).status_code == 422
    assert api.post(path, headers=headers(version=4), json={**body, "extra": 1}).status_code == 422
    assert [flow.occupant_command] == [None]

    added = api.post(path, headers=headers(version=4), json=body)
    assert added.status_code == 200, added.text
    assert added.headers["etag"] == '"5"'
    command = flow.occupant_command
    assert command is not None
    assert (command.lease_id, command.expected_lease_version) == (signed.lease_id, 4)
    assert (command.customer_id, command.occupancy_id) == (friend, occupancy_id)
    assert command.move_in_date == date(2026, 10, 20)
    assert command.authorization_reference == "reservations.complete"

    # Before the move-in the person is planned: no Occupancy and no date.
    planned = api.post(
        path,
        headers=headers(version=5),
        json={"event_id": str(uuid4()), "customer_id": str(friend), "reason": "Moves in too"},
    )
    assert planned.status_code == 200, planned.text
    assert flow.occupant_command is not None
    assert (flow.occupant_command.occupancy_id, flow.occupant_command.move_in_date) == (None, None)


def test_an_end_date_that_is_not_a_month_end_answers_its_own_code() -> None:
    """V1-056 slice 11a: the database refusal of BR-LEASE-031 reaches the screen by name."""
    from property_rental.lease import END_DATE_NOT_MONTH_END, LeaseEndDateNotMonthEndError

    property_id = uuid4()
    current = resource(property_id)

    class RefusingFlow(InMemoryLeaseFlow):
        def update_draft(
            self, command: LeaseUpdateDraftCommand, *, actor: AuthenticatedActor
        ) -> LeaseResource:
            raise LeaseEndDateNotMonthEndError(END_DATE_NOT_MONTH_END)

        def sign(self, command: LeaseSignCommand, *, actor: AuthenticatedActor) -> LeaseResource:
            raise LeaseEndDateNotMonthEndError(END_DATE_NOT_MONTH_END)

    api = client(
        RefusingFlow({current.lease_id: current}),
        actor(property_id, "leases.read", "leases.draft", "leases.sign"),
    )
    updated = api.patch(
        f"/api/v1/leases/{current.lease_id}",
        headers=headers(version=1),
        json={"event_id": str(uuid4()), "end_date": "2027-08-30", "reason": "Shorter Lease"},
    )
    signed = api.post(
        f"/api/v1/leases/{current.lease_id}/sign",
        headers=headers(version=1),
        json={"event_id": str(uuid4()), "reason": "All required Signers completed"},
    )
    for answer in (updated, signed):
        assert answer.status_code == 422
        error = answer.json()["error"]
        assert error["code"] == "LEASE_END_DATE_NOT_MONTH_END"
        assert error["fields"] == ["end_date"]
        assert error["rule_ids"] == ["BR-LEASE-031"]
        assert "calendar" not in answer.text
        assert answer.headers["cache-control"] == "private, no-store"
