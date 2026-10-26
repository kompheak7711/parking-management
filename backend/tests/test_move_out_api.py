"""HTTP boundary of the move-out and move-out inspection routes (V1-058 R3) with in-memory
flows."""

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_inspection import (
    InspectionFinding,
    MoveOutInspectionConflictError,
    MoveOutInspectionKeyReused,
    MoveOutInspectionResponse,
    RecordMoveOutInspection,
)
from property_rental.physical_move_out import (
    EndedOccupancy,
    PhysicalMoveOutAuthorizationError,
    PhysicalMoveOutNotFoundError,
    PhysicalMoveOutResolutionReliance,
    PhysicalMoveOutResponse,
    PhysicalMoveOutUnavailableError,
    PhysicalMoveOutUtilityConflictError,
    RecordPhysicalMoveOut,
)
from test_invoice import mutation_headers


class MemoryFlow:
    def __init__(self) -> None:
        self.commands: list[tuple[UUID, UUID, object]] = []
        self.reads: list[tuple[UUID, UUID, int, int]] = []
        self.failure: Exception | None = None

    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 20,
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
        command: RecordPhysicalMoveOut | RecordMoveOutInspection,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> PhysicalMoveOutResponse | MoveOutInspectionResponse:
        del actor
        if self.failure is not None:
            raise self.failure
        self.commands.append((property_id, lease_id, command))
        return PhysicalMoveOutResponse(
            201, {"data": {"lease_id": str(lease_id)}, "meta": {"request_id": request_id}}
        )


def client(move_out: MemoryFlow, inspection: MemoryFlow, signed_in: bool = True) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset({CapabilityGrant("leases.move_out", frozenset())}),
    )
    app = create_app(
        actor_resolver=lambda _: who if signed_in else None,
        move_out_flow=move_out,  # type: ignore[arg-type]
        move_out_inspection_flow=inspection,  # type: ignore[arg-type]
    )
    test_client = TestClient(app)
    test_client.cookies.set("__Host-prm_csrf", "csrf")
    return test_client


def move_out_body(event: UUID, termination: UUID, occupancy: UUID) -> dict[str, object]:
    return {
        "event_id": str(event),
        "termination_event_id": str(termination),
        "expected_lease_version": 6,
        "expected_unit_version": 3,
        "actual_move_out_date": "2026-10-31",
        "unit_condition": "CLEANING",
        "occupancies": [{"occupancy_id": str(occupancy), "expected_version": 2}],
        "reason": "Tenants handed back the keys",
        "authorization_reference": "Move-out recorded by the Manager",
        "evidence_reference": "Key hand-back form 31/10/2026",
        "supersedes_event_id": None,
    }


def inspection_body(inspection: UUID, finding: UUID) -> dict[str, object]:
    return {
        "inspection_id": str(inspection),
        "expected_lease_version": 6,
        "inspection_date": "2026-10-31",
        "result_text": "Joint inspection done with the tenant",
        "authorization_reference": "Inspection by the Manager",
        "evidence_reference": "Inspection form and 12 photos",
        "reason": "Move-out inspection",
        "findings": [
            {"finding_id": str(finding), "description": "Sofa scratched", "pet_related": True}
        ],
    }


def test_move_out_route_builds_the_exact_command_and_reads_the_page() -> None:
    flow, other = MemoryFlow(), MemoryFlow()
    http = client(flow, other)
    prop, lease, event, termination, occupancy, key = (uuid4() for _ in range(6))
    target = f"/api/v1/properties/{prop}/leases/{lease}/move-outs"
    reply = http.post(
        target,
        json=move_out_body(event, termination, occupancy),
        headers=mutation_headers(key=key),
    )
    assert reply.status_code == 201
    assert reply.json()["data"] == {"lease_id": str(lease)}
    assert flow.commands == [
        (
            prop,
            lease,
            RecordPhysicalMoveOut(
                idempotency_key=key,
                event_id=event,
                termination_event_id=termination,
                expected_lease_version=6,
                expected_unit_version=3,
                actual_move_out_date=date(2026, 10, 31),
                unit_condition="CLEANING",
                occupancies=(EndedOccupancy(occupancy, 2),),
                reason="Tenants handed back the keys",
                authorization_reference="Move-out recorded by the Manager",
                evidence_reference="Key hand-back form 31/10/2026",
            ),
        )
    ]
    assert other.commands == []
    assert http.get(f"{target}?limit=5&offset=0").json()["data"]["limit"] == 5
    assert flow.reads == [(prop, lease, 5, 0)]
    for bad in ("limit=0", "limit=21", "offset=-1", "other=1", "limit=5&limit=6"):
        assert http.get(f"{target}?{bad}").status_code == 400
    assert len(flow.reads) == 1


def test_inspection_route_builds_the_exact_command_and_reads_the_page() -> None:
    other, flow = MemoryFlow(), MemoryFlow()
    http = client(other, flow)
    prop, lease, inspection, finding, key = (uuid4() for _ in range(5))
    target = f"/api/v1/properties/{prop}/leases/{lease}/move-out-inspections"
    reply = http.post(
        target, json=inspection_body(inspection, finding), headers=mutation_headers(key=key)
    )
    assert reply.status_code == 201
    assert flow.commands == [
        (
            prop,
            lease,
            RecordMoveOutInspection(
                idempotency_key=key,
                inspection_id=inspection,
                expected_lease_version=6,
                inspection_date=date(2026, 10, 31),
                result_text="Joint inspection done with the tenant",
                authorization_reference="Inspection by the Manager",
                evidence_reference="Inspection form and 12 photos",
                reason="Move-out inspection",
                findings=(InspectionFinding(finding, "Sofa scratched", True),),
            ),
        )
    ]
    assert other.commands == []
    # No findings is a valid inspection: nothing was found.
    assert (
        http.post(
            target,
            json={**inspection_body(uuid4(), finding), "findings": []},
            headers=mutation_headers(),
        ).status_code
        == 201
    )
    assert http.get(target).status_code == 200
    assert flow.reads == [(prop, lease, 20, 0)]


def test_routes_refuse_bad_input_and_map_service_errors() -> None:
    move_out, inspection = MemoryFlow(), MemoryFlow()
    http = client(move_out, inspection)
    base = f"/api/v1/properties/{uuid4()}/leases/{uuid4()}"
    good = move_out_body(uuid4(), uuid4(), uuid4())
    same = uuid4()
    for bad in (
        {**good, "reason": " padded "},
        {**good, "unit_condition": "AVAILABLE"},
        {**good, "expected_unit_version": "3"},
        {**good, "occupancies": []},
        {**good, "actual_move_out_date": "31/10/2026"},
        {**good, "unexpected": "field"},
        # Two rows for one Occupancy fail in the command itself.
        {
            **good,
            "occupancies": [
                {"occupancy_id": str(same), "expected_version": 1},
                {"occupancy_id": str(same), "expected_version": 1},
            ],
        },
    ):
        assert (
            http.post(f"{base}/move-outs", json=bad, headers=mutation_headers()).status_code == 422
        )
    finding = uuid4()
    good_inspection = inspection_body(uuid4(), finding)
    for bad in (
        {**good_inspection, "result_text": ""},
        {
            **good_inspection,
            "findings": [{"finding_id": str(finding), "description": "x", "pet_related": "yes"}],
        },
        {key: value for key, value in good_inspection.items() if key != "findings"},
    ):
        assert (
            http.post(
                f"{base}/move-out-inspections", json=bad, headers=mutation_headers()
            ).status_code
            == 422
        )
    assert move_out.commands == [] and inspection.commands == []
    assert (
        http.post(f"{base}/move-outs?x=1", json=good, headers=mutation_headers()).status_code == 400
    )
    for failure, code in (
        (PhysicalMoveOutNotFoundError("x"), 404),
        (PhysicalMoveOutAuthorizationError("x"), 403),
        (PhysicalMoveOutUtilityConflictError("x"), 409),
        (PhysicalMoveOutResolutionReliance("x"), 409),
        (PhysicalMoveOutUnavailableError("x"), 503),
    ):
        move_out.failure = failure
        assert (
            http.post(f"{base}/move-outs", json=good, headers=mutation_headers()).status_code
            == code
        )
    for problem, code in (
        (MoveOutInspectionConflictError("x"), 409),
        (MoveOutInspectionKeyReused("x"), 409),
    ):
        inspection.failure = problem
        assert (
            http.post(
                f"{base}/move-out-inspections", json=good_inspection, headers=mutation_headers()
            ).status_code
            == code
        )


def test_routes_need_a_signed_in_browser_change_and_fail_closed_without_a_database() -> None:
    flow = MemoryFlow()
    base = f"/api/v1/properties/{uuid4()}/leases/{uuid4()}"
    assert client(flow, flow, signed_in=False).get(f"{base}/move-outs").status_code == 401
    # No Origin and CSRF pair: refused before the flow is called.
    body = move_out_body(uuid4(), uuid4(), uuid4())
    assert client(flow, flow).post(f"{base}/move-outs", json=body).status_code == 403
    assert flow.commands == []
    who = AuthenticatedActor(actor_id=str(uuid4()))
    bare = TestClient(create_app(actor_resolver=lambda _: who))
    assert bare.get(f"{base}/move-outs").status_code == 503
    assert bare.get(f"{base}/move-out-inspections").status_code == 503
