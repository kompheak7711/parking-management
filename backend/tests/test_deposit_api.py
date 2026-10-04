"""Corrected bounded V1-038 Deposit HTTP contracts."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.deposit import (
    CreatePetDepositCommand,
    DepositSnapshot,
    DepositType,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
    ReverseDepositDispositionCommand,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_api import (
    DepositLedgerEvent,
    DepositLedgerPage,
    PetDepartureResource,
    PetRefundReviewResource,
    PostgresDepositResourceFlow,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def snapshot(
    property_id: UUID, *, deposit_type: DepositType = DepositType.SECURITY
) -> DepositSnapshot:
    return DepositSnapshot(
        uuid4(),
        property_id,
        deposit_type,
        uuid4(),
        uuid4() if deposit_type is DepositType.SECURITY else None,
        uuid4() if deposit_type is DepositType.PET else None,
        uuid4() if deposit_type is DepositType.PET else None,
        50_000,
        20_000,
        20_000,
        30_000,
        1,
    )


@dataclass(slots=True)
class InMemoryDepositFlow:
    value: DepositSnapshot
    receipt_id: UUID = field(default_factory=uuid4)
    disposition_id: UUID = field(default_factory=uuid4)
    departure: PetDepartureResource | None = None
    review_value: PetRefundReviewResource | None = None
    last_command: object | None = None
    replacement_disposition_id: UUID | None = None
    expected_reservation_version: int | None = None

    def property_for_reservation(self, _: UUID) -> UUID:
        return self.value.property_id

    def property_for_lease(self, _: UUID) -> UUID:
        return self.value.property_id

    def property_for_receipt(self, _: UUID) -> UUID:
        return self.value.property_id

    def disposition_context(self, _: UUID) -> tuple[UUID, UUID | None]:
        return self.value.property_id, self.value.reservation_id

    def property_for_departure(self, _: UUID) -> UUID:
        return self.value.property_id

    def property_for_review(self, _: UUID) -> UUID:
        return self.value.property_id

    def list_for_reservation(self, _: UUID) -> tuple[DepositSnapshot, ...]:
        return (self.value,)

    def list_for_lease(self, _: UUID) -> tuple[DepositSnapshot, ...]:
        return (self.value,)

    def get(self, _: UUID) -> DepositSnapshot:
        return self.value

    def ledger(self, _: UUID, *, limit: int, cursor: str | None) -> DepositLedgerPage:
        del limit, cursor
        return DepositLedgerPage(
            (
                DepositLedgerEvent(
                    self.receipt_id,
                    "RECEIPT",
                    datetime(2026, 8, 26, tzinfo=UTC),
                    20_000,
                    uuid4(),
                    None,
                    None,
                    uuid4(),
                    None,
                    "USD",
                    20_000,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                ),
            ),
            None,
        )

    def create_pet_deposit(
        self, _: UUID, command: CreatePetDepositCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        del actor
        self.last_command = command
        self.value = replace(
            self.value,
            deposit_id=command.deposit_id,
            deposit_type=DepositType.PET,
            reservation_id=None,
            lease_id=command.lease_id,
            pet_approval_id=command.pet_approval_id,
            received_usd_cents=0,
            held_refundable_usd_cents=0,
        )
        return self.value

    def reverse_receipt(
        self, _: UUID, command: ReverseDepositReceiptCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        del actor
        self.last_command = command
        self.value = replace(self.value, received_usd_cents=0, held_refundable_usd_cents=0)
        return self.value

    def reverse_disposition(
        self,
        _: UUID,
        command: ReverseDepositDispositionCommand,
        *,
        replacement_disposition_id: UUID | None,
        expected_reservation_version: int | None,
        actor: AuthenticatedActor,
    ) -> DepositSnapshot:
        del actor
        self.last_command = command
        self.replacement_disposition_id = replacement_disposition_id
        self.expected_reservation_version = expected_reservation_version
        return self.value

    def record_departure(
        self, lease_id: UUID, command: RecordPetDepartureCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        del actor
        self.last_command = command
        self.departure = PetDepartureResource(
            command.departure_id,
            command.deposit_id,
            lease_id,
            self.value.pet_approval_id or uuid4(),
            command.permanently_left_date,
            command.reason,
            datetime(2026, 8, 26, tzinfo=UTC),
            uuid4(),
            None,
        )
        self.value = replace(self.value, pet_departure_id=command.departure_id)
        return self.value

    def qualify_review(
        self, _: UUID, command: QualifyPetDepositRefundReviewCommand, *, actor: AuthenticatedActor
    ) -> DepositSnapshot:
        del actor
        self.last_command = command
        self.value = replace(
            self.value, pet_refund_review_id=command.review_id, refund_qualified=True
        )
        return self.value

    def departures(self, _: UUID) -> tuple[PetDepartureResource, ...]:
        return () if self.departure is None else (self.departure,)

    def review(self, _: UUID) -> PetRefundReviewResource:
        assert self.review_value is not None
        return self.review_value


def client(flow: InMemoryDepositFlow, authenticated: AuthenticatedActor) -> TestClient:
    value = TestClient(
        create_app(actor_resolver=lambda _: authenticated, deposit_resource_flow=flow)
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def mutation_headers() -> dict[str, str]:
    return {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }


def test_postgres_deposit_reads_and_financial_commands_are_time_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    property_id = uuid4()
    value = snapshot(property_id)
    connect_options: list[dict[str, object]] = []
    statements: list[tuple[str, tuple[object, ...]]] = []
    resource = {
        "deposit_id": str(value.deposit_id),
        "property_id": str(value.property_id),
        "deposit_type": value.deposit_type.value,
        "customer_id": str(value.customer_id),
        "reservation_id": str(value.reservation_id),
        "lease_id": None,
        "pet_approval_id": None,
        "required_usd_cents": value.required_usd_cents,
        "received_usd_cents": value.received_usd_cents,
        "held_refundable_usd_cents": value.held_refundable_usd_cents,
        "outstanding_required_usd_cents": value.outstanding_required_usd_cents,
        "version": value.version,
    }

    class Result:
        def fetchone(self) -> tuple[object, ...]:
            return (resource,)

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Result:
            statements.append((" ".join(statement.split()), parameters))
            return Result()

    def connect(_: str, **options: object) -> Connection:
        connect_options.append(options)
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    flow = PostgresDepositResourceFlow("postgresql://runtime", "postgresql://financial")

    assert flow.get(value.deposit_id).deposit_id == value.deposit_id
    assert flow._financial_snapshot("SELECT resource", ()).deposit_id == value.deposit_id
    assert connect_options == [{"connect_timeout": 3}, {"connect_timeout": 3}]
    assert [parameters for statement, parameters in statements if "lock_timeout" in statement] == [
        ("3000",),
        ("3000",),
    ]
    assert [
        parameters for statement, parameters in statements if "statement_timeout" in statement
    ] == [("3000",), ("3000",)]


def test_deposit_reads_are_property_scoped_bounded_and_private() -> None:
    property_id = uuid4()
    value = snapshot(property_id)
    flow = InMemoryDepositFlow(value)
    api = client(flow, actor(property_id, "deposits.read"))

    response = api.get(f"/api/v1/reservations/{uuid4()}/deposits")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"][0]["deposit_type"] == "SECURITY"
    assert response.json()["data"][0]["can_reverse_receipt"] is False
    assert "can_reverse_disposition" not in response.json()["data"][0]
    assert response.json()["meta"]["can_manage"] is False
    assert response.json()["page"] == {"next_cursor": None, "limit": 10}
    ledger = api.get(f"/api/v1/deposits/{value.deposit_id}/ledger?limit=50")
    assert ledger.status_code == 200
    assert ledger.json()["data"][0]["event_kind"] == "RECEIPT"
    assert ledger.json()["data"][0]["can_reverse"] is False
    assert ledger.json()["page"] == {"next_cursor": None, "limit": 50}
    assert api.get(f"/api/v1/deposits/{value.deposit_id}/ledger?limit=101").status_code == 422
    denied = client(flow, actor(uuid4(), "deposits.read")).get(
        f"/api/v1/deposits/{value.deposit_id}"
    )
    assert denied.status_code == 404


def test_scope_correction_exposes_no_provisional_receipt_or_final_settlement_command() -> None:
    property_id = uuid4()
    api = client(InMemoryDepositFlow(snapshot(property_id)), actor(property_id, "deposits.read"))
    routes = cast(FastAPI, api.app).openapi()["paths"]
    assert "/api/v1/deposits/{id}/receipts" not in routes
    assert "/api/v1/final-settlements/{id}/deposit-dispositions" not in routes


def test_pet_liability_requires_csrf_and_exact_management_capability() -> None:
    property_id = uuid4()
    lease_id = uuid4()
    flow = InMemoryDepositFlow(snapshot(property_id, deposit_type=DepositType.PET))
    payload = {
        "deposit_id": str(uuid4()),
        "pet_approval_id": str(uuid4()),
        "required_usd_cents": 20_000,
        "required_effective_date": "2026-08-26",
        "reason": "Approved signed pet term",
    }
    denied = client(flow, actor(property_id, "deposits.read")).post(
        f"/api/v1/leases/{lease_id}/pet-deposits", json=payload, headers=mutation_headers()
    )
    assert denied.status_code == 404
    missing_csrf = client(flow, actor(property_id, "deposits.manage")).post(
        f"/api/v1/leases/{lease_id}/pet-deposits",
        json=payload,
        headers={"Origin": "https://localhost", "Idempotency-Key": str(uuid4())},
    )
    assert missing_csrf.status_code == 403
    created = client(flow, actor(property_id, "deposits.manage")).post(
        f"/api/v1/leases/{lease_id}/pet-deposits", json=payload, headers=mutation_headers()
    )
    assert created.status_code == 201
    assert created.headers["location"].endswith(str(flow.value.deposit_id))
    assert created.json()["data"]["new_receipt_creation_deferred"] is True
    managed_collection = client(flow, actor(property_id, "deposits.read", "deposits.manage")).get(
        f"/api/v1/leases/{lease_id}/deposits"
    )
    assert managed_collection.json()["meta"]["can_manage"] is True


def test_linked_reversals_and_split_pet_refund_qualification_preserve_sources() -> None:
    property_id = uuid4()
    lease_id = uuid4()
    value = snapshot(property_id, deposit_type=DepositType.PET)
    value = replace(value, lease_id=lease_id)
    flow = InMemoryDepositFlow(value)
    capabilities = ("deposits.read", "deposits.correct", "deposits.refund.qualify")
    api = client(flow, actor(property_id, *capabilities))

    reversed_receipt = api.post(
        f"/api/v1/deposit-receipts/{flow.receipt_id}/reverse",
        json={"reversal_id": str(uuid4()), "reason": "Verified duplicate"},
        headers=mutation_headers(),
    )
    assert reversed_receipt.status_code == 200
    departure_id = uuid4()
    departure = api.post(
        f"/api/v1/leases/{lease_id}/pet-departures",
        json={
            "departure_id": str(departure_id),
            "deposit_id": str(value.deposit_id),
            "permanently_left_date": "2026-08-26",
            "reason": "Approved pet permanently left",
        },
        headers=mutation_headers(),
    )
    assert departure.status_code == 201
    assert departure.json()["data"]["refund_qualified"] is False
    review = api.post(
        f"/api/v1/pet-departures/{departure_id}/refund-review",
        json={
            "review_id": str(uuid4()),
            "deposit_id": str(value.deposit_id),
            "obligations_reviewed_usd_cents": 0,
            "review_findings": "No remaining pet obligations",
            "resolution_reference": "inspection-2026-08-26",
            "reason": "Authorized active-Lease exception review",
        },
        headers=mutation_headers(),
    )
    assert review.status_code == 201
    assert review.json()["data"]["refund_qualified"] is True
    assert review.headers["location"].endswith(str(flow.value.pet_refund_review_id))


def test_mutations_conceal_cross_property_targets_before_command_execution() -> None:
    property_id = uuid4()
    flow = InMemoryDepositFlow(snapshot(property_id, deposit_type=DepositType.PET))
    api = client(
        flow,
        actor(uuid4(), "deposits.correct", "deposits.refund.qualify"),
    )
    reversed_receipt = api.post(
        f"/api/v1/deposit-receipts/{flow.receipt_id}/reverse",
        json={"reversal_id": str(uuid4()), "reason": "Verified duplicate"},
        headers=mutation_headers(),
    )
    departure = api.post(
        f"/api/v1/leases/{flow.value.lease_id}/pet-departures",
        json={
            "departure_id": str(uuid4()),
            "deposit_id": str(flow.value.deposit_id),
            "permanently_left_date": "2026-08-26",
            "reason": "Approved pet permanently left",
        },
        headers=mutation_headers(),
    )
    assert reversed_receipt.status_code == 404
    assert departure.status_code == 404
    assert flow.last_command is None


def test_reservation_disposition_correction_requires_replacement_and_exact_capabilities() -> None:
    property_id = uuid4()
    value = replace(snapshot(property_id), reservation_version=2)
    flow = InMemoryDepositFlow(value)
    api = client(
        flow,
        actor(
            property_id,
            "deposits.read",
            "reservation_deposits.correct",
            "reservation_deposits.dispose",
        ),
    )
    replacement_id = uuid4()
    response = api.post(
        f"/api/v1/deposit-dispositions/{flow.disposition_id}/reverse",
        json={
            "reversal_id": str(uuid4()),
            "replacement_disposition_id": str(replacement_id),
            "expected_reservation_version": 2,
            "reason": "Correct classified outcome evidence",
            "evidence_reference": "EVIDENCE-RESERVATION-1",
        },
        headers=mutation_headers(),
    )
    # V1-056 slice 3b: a Reservation outcome correction is a draft; this route records nothing.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESERVATION_DEPOSIT_DRAFT_REQUIRED"
    assert flow.replacement_disposition_id is None
    assert flow.expected_reservation_version is None

    split_capabilities = client(
        InMemoryDepositFlow(value),
        actor(property_id, "deposits.read", "deposits.correct"),
    ).get(f"/api/v1/deposits/{value.deposit_id}")
    assert split_capabilities.json()["data"]["can_reverse_receipt"] is True
    assert "can_reverse_disposition" not in split_capabilities.json()["data"]
