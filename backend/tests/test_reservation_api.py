"""API-032 through API-034 Reservation HTTP contract tests."""

from dataclasses import dataclass, field, replace
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    ReservationCancelCommand,
    ReservationCreateCommand,
    ReservationExtendCommand,
    ReservationLifecycleResult,
    ReservationStatus,
)
from property_rental.reservation_api import (
    PostgresReservationResourceFlow,
    ReservationExtensionNotice,
    ReservationPage,
    ReservationResource,
    ReservationResourceNotFound,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def resource(
    property_id: UUID,
    *,
    status: ReservationStatus = ReservationStatus.ACTIVE,
) -> ReservationResource:
    return ReservationResource(
        uuid4(),
        property_id,
        uuid4(),
        "101",
        uuid4(),
        "Customer One",
        date(2026, 8, 26),
        date(2026, 9, 5),
        date(2026, 9, 5),
        50_000,
        status,
        1,
        uuid4(),
        50_000,
        10_000,
        DepositOutcomeState.PENDING_V1_031,
        None,
        None,
        None,
        None,
        True,
    )


@dataclass(slots=True)
class InMemoryReservationFlow:
    resources: dict[UUID, ReservationResource] = field(default_factory=dict)
    create_command: ReservationCreateCommand | None = None
    extend_command: ReservationExtendCommand | None = None
    cancel_command: ReservationCancelCommand | None = None

    def list(
        self,
        property_id: UUID,
        *,
        reservation_status: ReservationStatus | None,
        limit: int,
        cursor: str | None,
    ) -> ReservationPage:
        del cursor
        items = tuple(
            item
            for item in self.resources.values()
            if item.property_id == property_id
            and (reservation_status is None or item.status is reservation_status)
        )
        return ReservationPage(items[:limit], None)

    def get(self, reservation_id: UUID) -> ReservationResource:
        try:
            return self.resources[reservation_id]
        except KeyError as exc:
            raise ReservationResourceNotFound from exc

    def create(
        self,
        property_id: UUID,
        command: ReservationCreateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.create_command = command
        value = ReservationResource(
            command.reservation_id,
            property_id,
            command.unit_id,
            "101",
            command.customer_id,
            "Customer One",
            command.reservation_date,
            command.original_expiration_date,
            command.original_expiration_date,
            command.agreed_monthly_rent_usd_cents,
            ReservationStatus.ACTIVE,
            1,
            command.deposit_id,
            command.required_deposit_usd_cents,
            command.accepted_required_amount_usd_cents,
            DepositOutcomeState.PENDING_V1_031,
            None,
            None,
            None,
            None,
            True,
        )
        self.resources[value.reservation_id] = value
        return value

    def extend(
        self,
        command: ReservationExtendCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.extend_command = command
        current = self.get(command.reservation_id)
        updated = replace(
            current,
            effective_expiration_date=command.new_expiration_date,
            version=current.version + 1,
            extension_notice=ReservationExtensionNotice(
                command.notice_id,
                current.effective_expiration_date,
                command.new_expiration_date,
                command.approved_at,
                command.reason_memo or None,
            ),
        )
        self.resources[updated.reservation_id] = updated
        return updated

    def cancel(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationResource:
        del actor
        self.cancel_command = command
        current = self.get(command.reservation_id)
        updated = replace(
            current,
            status=ReservationStatus.CANCELLED,
            version=current.version + 1,
            cancellation_reason_code=command.reason_code,
            cancellation_responsibility=command.responsibility,
            deposit_outcome_state=(
                DepositOutcomeState.NON_REFUNDABLE_DISPOSITION
                if command.responsibility is CancellationResponsibility.CUSTOMER
                else DepositOutcomeState.REFUND
            ),
        )
        self.resources[updated.reservation_id] = updated
        return updated

    def property_for_security_deposit_disposition(self, reservation_id: UUID) -> UUID:
        return self.get(reservation_id).property_id

    def create_security_deposit_disposition(
        self,
        command: ReservationCancelCommand,
        *,
        actor: AuthenticatedActor,
    ) -> ReservationLifecycleResult:
        updated = self.cancel(command, actor=actor)
        return ReservationLifecycleResult(
            updated.reservation_id,
            updated.unit_id,
            updated.status,
            command.reason_code,
            command.responsibility,
            updated.effective_expiration_date,
            updated.version,
            "VACANT",
            1,
            updated.deposit_id,
            updated.deposit_received_usd_cents,
            updated.deposit_outcome_state,
            command.outcome_id,
            command.refund_number,
        )


def headers(*, version: int | None = None) -> dict[str, str]:
    result = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    if version is not None:
        result["If-Match"] = f'"{version}"'
    return result


def client(flow: InMemoryReservationFlow, authenticated: AuthenticatedActor) -> TestClient:
    value = TestClient(
        create_app(actor_resolver=lambda _: authenticated, reservation_resource_flow=flow)
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def test_list_is_bounded_status_filtered_private_and_capability_sensitive() -> None:
    property_id = uuid4()
    active = resource(property_id)
    cancelled = replace(resource(property_id), status=ReservationStatus.CANCELLED)
    flow = InMemoryReservationFlow(
        {active.reservation_id: active, cancelled.reservation_id: cancelled}
    )
    response = client(flow, actor(property_id, "reservations.read", "reservations.create")).get(
        f"/properties/{property_id}/reservations?status=ACTIVE&limit=1"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"]["can_create"] is True
    assert [item["status"] for item in response.json()["data"]["items"]] == ["ACTIVE"]


def test_object_scope_is_not_disclosed_to_an_actor_from_another_property() -> None:
    property_id = uuid4()
    value = resource(property_id)
    flow = InMemoryReservationFlow({value.reservation_id: value})
    response = client(flow, actor(uuid4(), "reservations.read")).get(
        f"/reservations/{value.reservation_id}"
    )

    assert response.status_code == 404


def test_create_requires_csrf_and_preserves_client_idempotent_identity_and_trace() -> None:
    property_id = uuid4()
    authenticated = actor(property_id, "reservations.read", "reservations.create")
    flow = InMemoryReservationFlow()
    reservation_id = uuid4()
    payload = {
        "reservation_id": str(reservation_id),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-08-26",
        "agreed_monthly_rent_usd_cents": 50000,
        "expiration_date": "2026-09-05",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 10000,
        "required_security_deposit_usd_cents": 50000,
        "acceptance_reason": "Accepted normal suggestion",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
        "received_at": "2026-08-26T01:00:00Z",
    }
    api = client(flow, authenticated)
    rejected = api.post(
        f"/properties/{property_id}/reservations",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    accepted = api.post(
        f"/properties/{property_id}/reservations",
        json=payload,
        headers=headers(),
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 201
    assert accepted.headers["location"] == f"/reservations/{reservation_id}"
    assert flow.create_command is not None
    assert flow.create_command.calculation_trace["suggested_amount_usd_cents"] == 10000
    assert flow.create_command.acceptance_kind == "NORMAL_SUGGESTION"


def test_authorized_variance_requires_separate_capability() -> None:
    property_id = uuid4()
    payload = {
        "reservation_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "reservation_date": "2026-08-26",
        "agreed_monthly_rent_usd_cents": 50000,
        "expiration_date": "2026-09-05",
        "acceptance_id": str(uuid4()),
        "accepted_initial_deposit_usd_cents": 9000,
        "required_security_deposit_usd_cents": 50000,
        "acceptance_reason": "Approved variance",
        "deposit_id": str(uuid4()),
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
        "received_at": "2026-08-26T01:00:00Z",
    }
    missing = client(InMemoryReservationFlow(), actor(property_id, "reservations.create")).post(
        f"/properties/{property_id}/reservations", json=payload, headers=headers()
    )
    permitted_flow = InMemoryReservationFlow()
    permitted = client(
        permitted_flow,
        actor(property_id, "reservations.create", "reservation_deposits.override"),
    ).post(f"/properties/{property_id}/reservations", json=payload, headers=headers())

    assert missing.status_code == 404
    assert permitted.status_code == 201
    assert permitted_flow.create_command is not None
    assert permitted_flow.create_command.acceptance_kind == "AUTHORIZED_VARIANCE"


def test_extend_requires_version_and_records_one_notice_shape() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(flow, actor(property_id, "reservations.read", "reservations.extend"))
    payload = {
        "notice_id": str(uuid4()),
        "new_expiration_date": "2026-09-12",
        "approved_at": "2026-09-01T01:00:00Z",
        "reason_memo": "Approved extension",
    }
    missing = api.post(
        f"/reservations/{current.reservation_id}/extend", json=payload, headers=headers()
    )
    accepted = api.post(
        f"/reservations/{current.reservation_id}/extend",
        json=payload,
        headers=headers(version=1),
    )

    assert missing.status_code == 428
    assert accepted.status_code == 200
    assert flow.extend_command is not None
    assert flow.extend_command.authorization_reference == "reservations.extend"
    assert accepted.json()["data"]["extension_notice"]["new_expiration_date"] == "2026-09-12"


def test_cancel_derives_customer_deposit_disposition_without_free_form_outcome() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(
            property_id,
            "reservations.read",
            "reservations.cancel",
            "reservation_deposits.dispose",
        ),
    )
    response = api.post(
        f"/reservations/{current.reservation_id}/cancel",
        headers=headers(version=1),
        json={
            "event_id": str(uuid4()),
            "outcome_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
            "refund_number": None,
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "Cookie" in response.headers["vary"]
    assert flow.cancel_command is not None
    assert flow.cancel_command.outcome_authorization_reference == "reservation_deposits.dispose"
    assert response.json()["data"]["deposit_outcome_state"] == "NON_REFUNDABLE_DISPOSITION"


def test_explicit_security_deposit_disposition_route_reuses_atomic_cancellation() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.cancel", "reservation_deposits.dispose"),
    )
    response = api.post(
        f"/api/v1/reservations/{current.reservation_id}/security-deposit-dispositions",
        headers=headers(version=1),
        json={
            "event_id": str(uuid4()),
            "outcome_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
            "refund_number": None,
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert flow.cancel_command is not None
    assert flow.cancel_command.outcome_authorization_reference == "reservation_deposits.dispose"
    assert response.json()["data"] == {
        "reservation_id": str(current.reservation_id),
        "unit_id": str(current.unit_id),
        "status": "CANCELLED",
        "cancellation_reason_code": "CUSTOMER_WITHDREW",
        "cancellation_responsibility": "CUSTOMER",
        "effective_expiration_date": current.effective_expiration_date.isoformat(),
        "version": 2,
        "unit_status": "VACANT",
        "unit_version": 1,
        "deposit_id": str(current.deposit_id),
        "deposit_received_usd_cents": current.deposit_received_usd_cents,
        "deposit_outcome_state": "NON_REFUNDABLE_DISPOSITION",
        "outcome_id": response.json()["data"]["outcome_id"],
        "refund_number": None,
    }


def test_postgres_security_disposition_route_is_time_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    actor_id = uuid4()
    reservation_id = uuid4()
    unit_id = uuid4()
    deposit_id = uuid4()
    outcome_id = uuid4()
    connect_options: list[dict[str, object]] = []
    statements: list[tuple[str, tuple[object, ...]]] = []

    class Result:
        def __init__(self, row: tuple[object, ...]) -> None:
            self.row = row

        def fetchone(self) -> tuple[object, ...]:
            return self.row

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Result:
            normalized = " ".join(statement.split())
            statements.append((normalized, parameters))
            if "cancel_reservation_v2" in normalized:
                return Result(
                    (
                        reservation_id,
                        unit_id,
                        "CANCELLED",
                        "CUSTOMER_WITHDREW",
                        "CUSTOMER",
                        date(2026, 9, 5),
                        2,
                        "VACANT",
                        1,
                        deposit_id,
                        10_000,
                        "NON_REFUNDABLE_DISPOSITION",
                        outcome_id,
                        None,
                    )
                )
            return Result((property_id,))

    def connect(_: str, **options: object) -> Connection:
        connect_options.append(options)
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    flow = PostgresReservationResourceFlow("postgresql://runtime", "postgresql://financial")
    authenticated = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {
                CapabilityGrant("reservations.cancel", frozenset({str(property_id)})),
                CapabilityGrant("reservation_deposits.dispose", frozenset({str(property_id)})),
            }
        ),
    )
    result = flow.create_security_deposit_disposition(
        ReservationCancelCommand(
            uuid4(),
            uuid4(),
            outcome_id,
            reservation_id,
            1,
            "CUSTOMER_WITHDREW",
            CancellationResponsibility.CUSTOMER,
            True,
            "Customer request",
            None,
            "reservations.cancel",
            "reservation_deposits.dispose",
            None,
        ),
        actor=authenticated,
    )

    assert result.outcome_id == outcome_id
    assert connect_options == [{"connect_timeout": 3}, {"connect_timeout": 3}]
    assert [parameters for statement, parameters in statements if "lock_timeout" in statement] == [
        ("3000",),
        ("3000",),
    ]
    assert [
        parameters for statement, parameters in statements if "statement_timeout" in statement
    ] == [("3000",), ("3000",)]


def test_explicit_security_deposit_disposition_requires_precondition_without_caching() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.cancel", "reservation_deposits.dispose"),
    )
    response = api.post(
        f"/api/v1/reservations/{current.reservation_id}/security-deposit-dispositions",
        headers=headers(),
        json={
            "event_id": str(uuid4()),
            "outcome_id": str(uuid4()),
            "reason_code": "CUSTOMER_WITHDREW",
            "responsibility": "CUSTOMER",
            "property_could_provide_unit": True,
            "reason_memo": "Customer request",
            "coordination_reference": None,
            "refund_number": None,
        },
    )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "PRECONDITION_FAILED"
    assert response.headers["cache-control"] == "private, no-store"
    assert "Cookie" in response.headers["vary"]
    assert flow.cancel_command is None


def test_no_generic_status_patch_and_move_in_requires_v1_036_command_schema() -> None:
    property_id = uuid4()
    current = resource(property_id)
    flow = InMemoryReservationFlow({current.reservation_id: current})
    api = client(
        flow,
        actor(property_id, "reservations.read", "reservations.complete"),
    )

    patch_response = api.patch(
        f"/reservations/{current.reservation_id}", json={"status": "CANCELLED"}
    )
    assert patch_response.status_code == 405
    assert api.post(f"/reservations/{current.reservation_id}/complete-move-in").status_code == 404
