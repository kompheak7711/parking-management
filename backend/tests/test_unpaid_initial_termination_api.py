"""HTTP boundary of the unpaid Initial termination follow-up with an in-memory flow."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.unpaid_initial_termination import (
    CreditMovedInInitialRentCommand,
    ResolveNeverMovedInCommand,
    UnpaidInitialTerminationConflictError,
    UnpaidInitialTerminationNotFoundError,
)
from test_invoice import mutation_headers


class MemoryFlow:
    def __init__(self) -> None:
        self.commands: list[object] = []
        self.failure: Exception | None = None

    def _record(self, command: object) -> dict[str, object]:
        if self.failure is not None:
            raise self.failure
        self.commands.append(command)
        return {"path": "RECORDED"}

    def resolve_never_moved_in(
        self, property_id: UUID, command: ResolveNeverMovedInCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        del property_id, actor
        return self._record(command)

    def credit_moved_in_initial_rent(
        self,
        property_id: UUID,
        command: CreditMovedInInitialRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, actor
        return self._record(command)


def client(flow: MemoryFlow, signed_in: bool = True) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset({CapabilityGrant("leases.terminate", frozenset())}),
    )
    app = create_app(actor_resolver=lambda _: who if signed_in else None, unpaid_initial_flow=flow)
    test_client = TestClient(app)
    test_client.cookies.set("__Host-prm_csrf", "csrf")
    return test_client


def path(kind: str, property_id: UUID | None = None, event: UUID | None = None) -> str:
    return (
        f"/api/v1/properties/{property_id or uuid4()}/lease-terminations/{event or uuid4()}"
        f"/unpaid-initial-{kind}"
    )


def test_never_moved_in_route_builds_the_exact_command_and_hides_nothing_in_the_reply() -> None:
    flow = MemoryFlow()
    event, resolution, key = uuid4(), uuid4(), uuid4()
    reply = client(flow).post(
        path("never-moved-in", event=event),
        json={
            "resolution_id": str(resolution),
            "unit_status": "CLEANING",
            "unit_status_reason": "Needs cleaning",
            "reason": "Never moved in",
        },
        headers=mutation_headers(key=key),
    )
    assert reply.status_code == 201
    assert reply.headers["cache-control"] == "private, no-store"
    assert reply.json()["data"] == {"path": "RECORDED"}
    assert flow.commands == [
        ResolveNeverMovedInCommand(
            key, resolution, event, "CLEANING", "Never moved in", "Needs cleaning"
        )
    ]


def test_credit_route_builds_the_exact_command() -> None:
    flow = MemoryFlow()
    event, resolution, key = uuid4(), uuid4(), uuid4()
    reply = client(flow).post(
        path("moved-in-credit", event=event),
        json={"resolution_id": str(resolution), "reason": "Rent after termination"},
        headers=mutation_headers(key=key),
    )
    assert reply.status_code == 201
    assert flow.commands == [
        CreditMovedInInitialRentCommand(key, resolution, event, "Rent after termination")
    ]


def test_routes_refuse_invalid_input_without_calling_the_flow() -> None:
    flow = MemoryFlow()
    http = client(flow)
    good = {"resolution_id": str(uuid4()), "unit_status": "VACANT", "reason": "Never moved in"}
    target = path("never-moved-in")
    for bad in (
        {**good, "unit_status": "OCCUPIED"},
        {**good, "reason": " padded "},
        {**good, "unexpected": "field"},
        {**good, "resolution_id": "not-a-uuid"},
        {key: value for key, value in good.items() if key != "reason"},
    ):
        assert http.post(target, json=bad, headers=mutation_headers()).status_code == 422
    # CLEANING without a Unit reason and VACANT with one fail in the command itself.
    assert (
        http.post(
            target, json={**good, "unit_status": "CLEANING"}, headers=mutation_headers()
        ).status_code
        == 422
    )
    assert (
        http.post(
            target, json={**good, "unit_status_reason": "Unneeded"}, headers=mutation_headers()
        ).status_code
        == 422
    )
    assert http.post(target + "?force=1", json=good, headers=mutation_headers()).status_code == 400
    assert flow.commands == []


def test_routes_need_a_session_browser_origin_and_csrf_token() -> None:
    flow = MemoryFlow()
    body = {"resolution_id": str(uuid4()), "reason": "Rent after termination"}
    target = path("moved-in-credit")
    assert (
        client(flow, signed_in=False)
        .post(target, json=body, headers=mutation_headers())
        .status_code
        == 401
    )
    http = client(flow)
    no_csrf = mutation_headers()
    no_csrf.pop("X-CSRF-Token")
    assert http.post(target, json=body, headers=no_csrf).status_code == 403
    foreign = {**mutation_headers(), "Origin": "https://untrusted.example"}
    assert http.post(target, json=body, headers=foreign).status_code == 403
    no_key = mutation_headers()
    no_key.pop("Idempotency-Key")
    assert http.post(target, json=body, headers=no_key).status_code == 422
    assert flow.commands == []


def test_service_failures_map_to_not_found_and_conflict() -> None:
    flow = MemoryFlow()
    http = client(flow)
    body = {"resolution_id": str(uuid4()), "reason": "Rent after termination"}
    target = path("moved-in-credit")
    flow.failure = UnpaidInitialTerminationNotFoundError("missing")
    assert http.post(target, json=body, headers=mutation_headers()).status_code == 404
    flow.failure = UnpaidInitialTerminationConflictError("conflict")
    assert http.post(target, json=body, headers=mutation_headers()).status_code == 409
