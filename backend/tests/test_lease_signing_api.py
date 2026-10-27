"""HTTP boundary of the signing routes (V1-060 B6, DL-100) with an in-memory flow."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.api_refusals import RefusedRequest
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_signing_api import (
    PARTIAL_SERVICE,
    InitialRentInvoice,
    LeaseSigningNotFound,
)
from test_invoice import mutation_headers

PROPERTY = uuid4()


class MemoryFlow:
    def __init__(self) -> None:
        self.plans: list[tuple[UUID, UUID, UUID, UUID, int, str]] = []
        self.invoices: list[tuple[UUID, UUID, UUID, UUID]] = []
        self.failure: Exception | None = None

    def property_of(self, lease_id: UUID) -> UUID:
        if self.failure is not None and isinstance(self.failure, LeaseSigningNotFound):
            raise self.failure
        return PROPERTY

    def preview(self, property_id: UUID, lease_id: UUID) -> dict[str, object]:
        return {"initial": None, "planned_security_deposit_usd_cents": 50_000}

    def set_planned_deposit(
        self,
        property_id: UUID,
        lease_id: UUID,
        plan_id: UUID,
        actor_id: UUID,
        required_usd_cents: int,
        reason: str,
    ) -> int:
        self.plans.append((property_id, lease_id, plan_id, actor_id, required_usd_cents, reason))
        return required_usd_cents

    def initial_invoice(
        self, property_id: UUID, lease_id: UUID, idempotency_key: UUID, actor_id: UUID
    ) -> InitialRentInvoice:
        if self.failure is not None:
            raise self.failure
        self.invoices.append((property_id, lease_id, idempotency_key, actor_id))
        return InitialRentInvoice(UUID(int=7), created=True)


def client(flow: MemoryFlow, *capabilities: str) -> tuple[TestClient, UUID]:
    actor = uuid4()
    who = AuthenticatedActor(
        actor_id=str(actor),
        capability_grants=frozenset(
            CapabilityGrant(name, frozenset({str(PROPERTY)})) for name in capabilities
        ),
    )
    app = create_app(actor_resolver=lambda _: who, lease_signing_flow=flow)
    test_client = TestClient(app)
    test_client.cookies.set("__Host-prm_csrf", "csrf")
    return test_client, actor


def test_the_signing_preview_needs_lease_read() -> None:
    flow = MemoryFlow()
    lease = uuid4()
    http, _ = client(flow, "leases.read")
    reply = http.get(f"/api/v1/leases/{lease}/signing-preview")
    assert reply.status_code == 200
    assert reply.json()["data"]["planned_security_deposit_usd_cents"] == 50_000
    assert reply.headers["Cache-Control"] == "private, no-store"
    assert http.get(f"/api/v1/leases/{lease}/signing-preview?x=1").status_code == 400
    nobody, _ = client(flow)
    assert nobody.get(f"/api/v1/leases/{lease}/signing-preview").status_code == 404


def test_the_planned_security_deposit_is_saved_with_lease_draft_only() -> None:
    flow = MemoryFlow()
    lease, plan = uuid4(), uuid4()
    http, actor = client(flow, "leases.draft")
    body = {"plan_id": str(plan), "required_usd_cents": 60_000, "reason": "Draft Lease terms"}
    reply = http.put(
        f"/api/v1/leases/{lease}/planned-security-deposit", json=body, headers=mutation_headers()
    )
    assert reply.status_code == 200
    assert reply.json()["data"] == {"planned_security_deposit_usd_cents": 60_000}
    assert flow.plans == [(PROPERTY, lease, plan, actor, 60_000, "Draft Lease terms")]
    for bad in (
        {**body, "required_usd_cents": 0},
        {**body, "required_usd_cents": "600"},
        {**body, "reason": ""},
        {**body, "extra": 1},
    ):
        assert (
            http.put(
                f"/api/v1/leases/{lease}/planned-security-deposit",
                json=bad,
                headers=mutation_headers(),
            ).status_code
            == 422
        )
    signer, _ = client(flow, "leases.sign")
    assert (
        signer.put(
            f"/api/v1/leases/{lease}/planned-security-deposit",
            json=body,
            headers=mutation_headers(),
        ).status_code
        == 404
    )
    assert len(flow.plans) == 1


def test_the_initial_rent_invoice_needs_lease_sign_and_shows_a_refusal() -> None:
    flow = MemoryFlow()
    lease, key = uuid4(), uuid4()
    http, actor = client(flow, "leases.sign")
    reply = http.post(
        f"/api/v1/leases/{lease}/initial-rent-invoice", headers=mutation_headers(key=key)
    )
    assert reply.status_code == 200
    assert reply.json()["data"] == {"invoice_id": str(UUID(int=7)), "created": True}
    assert flow.invoices == [(PROPERTY, lease, key, actor)]
    flow.failure = RefusedRequest(PARTIAL_SERVICE)
    refused = http.post(f"/api/v1/leases/{lease}/initial-rent-invoice", headers=mutation_headers())
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "INITIAL_RENT_SERVICE_PART_MONTH"
    drafter, _ = client(flow, "leases.draft")
    assert (
        drafter.post(
            f"/api/v1/leases/{lease}/initial-rent-invoice", headers=mutation_headers()
        ).status_code
        == 404
    )
    flow.failure = LeaseSigningNotFound()
    assert (
        http.post(
            f"/api/v1/leases/{lease}/initial-rent-invoice", headers=mutation_headers()
        ).status_code
        == 404
    )
