"""HTTP boundary of the termination notice routes (V1-058 R3) with an in-memory flow."""

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_notices import (
    LeaseNoticeConflictError,
    LeaseNoticeKeyReused,
    LeaseNoticeNotFoundError,
    LeaseNoticeResponse,
    LeaseNoticeUnavailableError,
    RecordLeaseNotice,
)
from test_invoice import mutation_headers


class MemoryFlow:
    def __init__(self) -> None:
        self.commands: list[tuple[UUID, UUID, RecordLeaseNotice]] = []
        self.reads: list[tuple[UUID, UUID, int, int]] = []
        self.failure: Exception | None = None

    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        del actor
        if self.failure is not None:
            raise self.failure
        self.reads.append((property_id, lease_id, limit, offset))
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordLeaseNotice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseNoticeResponse:
        del actor
        if self.failure is not None:
            raise self.failure
        self.commands.append((property_id, lease_id, command))
        return LeaseNoticeResponse(
            201,
            {"data": {"id": str(command.notice_id)}, "meta": {"request_id": request_id}},
        )


def client(flow: MemoryFlow, signed_in: bool = True) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset({CapabilityGrant("leases.terminate", frozenset())}),
    )
    app = create_app(actor_resolver=lambda _: who if signed_in else None, lease_notice_flow=flow)
    test_client = TestClient(app)
    test_client.cookies.set("__Host-prm_csrf", "csrf")
    return test_client


def body(notice: UUID) -> dict[str, object]:
    return {
        "notice_id": str(notice),
        "expected_lease_version": 4,
        "notice_date": "2026-10-25",
        "intended_termination_date": "2026-11-24",
        "notice_text": "The Lease ends on 24/11/2026 because the Rent is not paid.",
        "governing_lease_provision": "Lease article 2.5",
        "approved_grounds": "Rent unpaid after the day-30 default notice",
        "notice_period_terms": "30 days",
        "evidence_reference": "Letter L-2026-011",
        "communication_record": "Handed to the tenant: signed our copy",
        "authorization_reference": "Termination notice given by the Owner",
        "reason": "Termination notice given",
    }


def test_record_route_builds_the_exact_command_and_returns_the_saved_reply() -> None:
    flow = MemoryFlow()
    prop, lease, notice, key = uuid4(), uuid4(), uuid4(), uuid4()
    reply = client(flow).post(
        f"/api/v1/properties/{prop}/leases/{lease}/termination-notices",
        json=body(notice),
        headers=mutation_headers(key=key),
    )
    assert reply.status_code == 201
    assert reply.json()["data"] == {"id": str(notice)}
    assert flow.commands == [
        (
            prop,
            lease,
            RecordLeaseNotice(
                idempotency_key=key,
                notice_id=notice,
                expected_lease_version=4,
                notice_date=date(2026, 10, 25),
                intended_termination_date=date(2026, 11, 24),
                notice_text="The Lease ends on 24/11/2026 because the Rent is not paid.",
                governing_lease_provision="Lease article 2.5",
                approved_grounds="Rent unpaid after the day-30 default notice",
                notice_period_terms="30 days",
                evidence_reference="Letter L-2026-011",
                communication_record="Handed to the tenant: signed our copy",
                authorization_reference="Termination notice given by the Owner",
                reason="Termination notice given",
            ),
        )
    ]


def test_read_route_pages_the_notices_of_the_lease() -> None:
    flow = MemoryFlow()
    prop, lease = uuid4(), uuid4()
    http = client(flow)
    reply = http.get(
        f"/api/v1/properties/{prop}/leases/{lease}/termination-notices?limit=20&offset=0"
    )
    assert reply.status_code == 200
    assert reply.json()["data"]["items"] == []
    assert flow.reads == [(prop, lease, 20, 0)]
    for bad in ("limit=0", "limit=101", "offset=-1", "other=1", "limit=5&limit=6"):
        assert (
            http.get(f"/api/v1/properties/{prop}/leases/{lease}/termination-notices?{bad}")
        ).status_code == 400
    assert len(flow.reads) == 1


def test_record_route_refuses_bad_input_and_maps_service_errors() -> None:
    flow = MemoryFlow()
    http = client(flow)
    target = f"/api/v1/properties/{uuid4()}/leases/{uuid4()}/termination-notices"
    good = body(uuid4())
    for bad in (
        {**good, "reason": " padded "},
        {**good, "expected_lease_version": 0},
        {**good, "expected_lease_version": "4"},
        {**good, "notice_date": "25/10/2026"},
        {**good, "unexpected": "field"},
        {key: value for key, value in good.items() if key != "notice_text"},
        # The intended date before the notice fails in the command itself.
        {**good, "intended_termination_date": "2026-10-24"},
    ):
        assert http.post(target, json=bad, headers=mutation_headers()).status_code == 422
    assert flow.commands == []
    assert http.post(f"{target}?x=1", json=good, headers=mutation_headers()).status_code == 400
    for failure, code in (
        (LeaseNoticeNotFoundError("x"), 404),
        (LeaseNoticeConflictError("x"), 409),
        (LeaseNoticeKeyReused("x"), 409),
        (LeaseNoticeUnavailableError("x"), 503),
    ):
        flow.failure = failure
        assert http.post(target, json=good, headers=mutation_headers()).status_code == code


def test_routes_need_a_signed_in_browser_change() -> None:
    flow = MemoryFlow()
    target = f"/api/v1/properties/{uuid4()}/leases/{uuid4()}/termination-notices"
    assert client(flow, signed_in=False).get(target).status_code == 401
    # No Origin and CSRF pair: refused before the flow is called.
    assert client(flow).post(target, json=body(uuid4())).status_code == 403
    assert flow.commands == []
