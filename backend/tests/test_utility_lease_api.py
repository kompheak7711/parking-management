"""HTTP boundary of the Utility baseline, final input, final and catch-up Invoice routes."""

from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.final_utility_invoice import (
    CatchUpUtilityInvoice,
    CreateFinalUtilityInvoice,
    FinalUtilityInvoiceConflictError,
    FinalUtilityInvoiceInvalidError,
    FinalUtilityInvoiceKeyReused,
    UtilityInvoiceResponse,
)
from property_rental.identity import AuthenticatedActor
from property_rental.move_out_final_inputs import (
    MoveOutFinalInputsNotFoundError,
    MoveOutFinalInputsResponse,
    RecordMoveOutFinalInputs,
)
from property_rental.utility_baseline import (
    RecordUtilityBaseline,
    UtilityBaselineAuthorizationError,
    UtilityBaselineResponse,
)
from test_invoice import mutation_headers


class MemoryFlow:
    def __init__(self) -> None:
        self.commands: list[object] = []
        self.failure: Exception | None = None
        self.pages: list[tuple[str, int, int]] = []

    def _check(self) -> None:
        if self.failure is not None:
            raise self.failure

    def baseline_read(self, property_id: UUID, lease_id: UUID, **kwargs: Any) -> dict[str, object]:
        self._check()
        self.pages.append(("baseline", kwargs["limit"], kwargs["offset"]))
        return {"items": [], "total": 0}

    def baseline_record(
        self, property_id: UUID, lease_id: UUID, command: RecordUtilityBaseline, **kwargs: Any
    ) -> UtilityBaselineResponse:
        self._check()
        self.commands.append(command)
        return UtilityBaselineResponse(201, {"data": {"event_id": str(command.event_id)}})

    def final_inputs_read(
        self, property_id: UUID, lease_id: UUID, **kwargs: Any
    ) -> dict[str, object]:
        self._check()
        self.pages.append(("inputs", kwargs["limit"], kwargs["offset"]))
        return {"items": [], "total": 0}

    def final_inputs_record(
        self, property_id: UUID, lease_id: UUID, command: RecordMoveOutFinalInputs, **kwargs: Any
    ) -> MoveOutFinalInputsResponse:
        self._check()
        self.commands.append(command)
        return MoveOutFinalInputsResponse(201, {"data": {"event_id": str(command.event_id)}})

    def create_final(
        self, property_id: UUID, lease_id: UUID, command: CreateFinalUtilityInvoice, **kwargs: Any
    ) -> UtilityInvoiceResponse:
        self._check()
        self.commands.append(command)
        return UtilityInvoiceResponse(201, {"data": {"invoice_id": str(command.invoice_id)}})

    def catch_up(
        self, property_id: UUID, lease_id: UUID, command: CatchUpUtilityInvoice, **kwargs: Any
    ) -> UtilityInvoiceResponse:
        self._check()
        self.commands.append(command)
        return UtilityInvoiceResponse(201, {"data": {"invoice_id": str(command.invoice_id)}})

    def unbilled_periods(self, property_id: UUID, **kwargs: Any) -> dict[str, object]:
        self._check()
        self.pages.append(("unbilled", kwargs["limit"], kwargs["offset"]))
        return {"items": []}


def client(flow: MemoryFlow, signed_in: bool = True) -> TestClient:
    who = AuthenticatedActor(actor_id=str(uuid4()), capability_grants=frozenset())
    app = create_app(actor_resolver=lambda _: who if signed_in else None, utility_lease_flow=flow)
    http = TestClient(app)
    http.cookies.set("__Host-prm_csrf", "csrf")
    return http


def base(kind: str) -> str:
    return f"/api/v1/properties/{uuid4()}/leases/{uuid4()}/{kind}"


def test_every_command_route_builds_its_exact_command_and_answers_201() -> None:
    flow = MemoryFlow()
    http = client(flow)
    event, key = uuid4(), uuid4()
    meter, reading = uuid4(), uuid4()
    baseline = http.post(
        base("utility-baseline"),
        json={
            "event_id": str(event),
            "baseline_date": "2026-09-02",
            "reason": "Baseline",
            "evidence_reference": "Sheet 1",
            "items": [{"meter_id": str(meter), "reading_id": str(reading)}],
        },
        headers=mutation_headers(key=key),
    )
    inputs = http.post(
        base("move-out-final-utility-inputs"),
        json={
            "event_id": str(event),
            "move_out_event_id": str(uuid4()),
            "reason": "Reviewed",
            "authorization_reference": "Authorized",
            "evidence_reference": "Sheet 2",
            "items": [
                {"meter_id": str(meter), "resolution": "READING", "reading_id": str(reading)}
            ],
        },
        headers=mutation_headers(key=key),
    )
    final = http.post(
        base("final-utility-invoice"),
        json={
            "invoice_id": str(uuid4()),
            "final_input_event_id": str(event),
            "due_date": "2026-10-20",
            "due_date_reason": "Owner agreed",
        },
        headers=mutation_headers(key=key),
    )
    catch_up = http.post(
        base("utility-catch-up-invoice"),
        json={"invoice_id": str(uuid4()), "consumption_period_id": str(uuid4())},
        headers=mutation_headers(key=key),
    )
    for reply in (baseline, inputs, final, catch_up):
        assert reply.status_code == 201, reply.text
        assert reply.headers["cache-control"] == "private, no-store"
    kinds = [type(command).__name__ for command in flow.commands]
    assert kinds == [
        "RecordUtilityBaseline",
        "RecordMoveOutFinalInputs",
        "CreateFinalUtilityInvoice",
        "CatchUpUtilityInvoice",
    ]
    assert all(command.idempotency_key == key for command in flow.commands)  # type: ignore[attr-defined]


def test_routes_refuse_invalid_bodies_and_queries_without_calling_the_flow() -> None:
    flow = MemoryFlow()
    http = client(flow)
    catch_up = base("utility-catch-up-invoice")
    good = {"invoice_id": str(uuid4()), "consumption_period_id": str(uuid4())}
    for bad in (
        {**good, "unexpected": "field"},
        {**good, "invoice_id": "not-a-uuid"},
        {**good, "due_date": "2026-10-20", "due_date_reason": " padded "},
        {"invoice_id": good["invoice_id"]},
    ):
        assert http.post(catch_up, json=bad, headers=mutation_headers()).status_code == 422
    # A Due Date without its reason is rejected by the command, not forwarded.
    assert (
        http.post(
            catch_up, json={**good, "due_date": "2026-10-20"}, headers=mutation_headers()
        ).status_code
        == 422
    )
    assert (
        http.post(catch_up + "?force=1", json=good, headers=mutation_headers()).status_code == 400
    )
    assert http.get(base("utility-baseline") + "?limit=21").status_code == 422
    assert http.get(base("utility-baseline") + "?force=1").status_code == 400
    assert (
        http.get(f"/api/v1/properties/{uuid4()}/unbilled-utility-periods?limit=51").status_code
        == 422
    )
    assert flow.commands == []


def test_reads_pass_the_bounded_page_through() -> None:
    flow = MemoryFlow()
    http = client(flow)
    assert http.get(base("utility-baseline") + "?limit=5&offset=10").status_code == 200
    assert http.get(base("move-out-final-utility-inputs")).status_code == 200
    reply = http.get(f"/api/v1/properties/{uuid4()}/unbilled-utility-periods?limit=7")
    assert reply.status_code == 200 and reply.json()["data"] == {"items": []}
    assert flow.pages == [("baseline", 5, 10), ("inputs", 20, 0), ("unbilled", 7, 0)]


def test_routes_need_a_session_origin_csrf_and_idempotency_key() -> None:
    flow = MemoryFlow()
    body = {"invoice_id": str(uuid4()), "consumption_period_id": str(uuid4())}
    path = base("utility-catch-up-invoice")
    assert (
        client(flow, signed_in=False).post(path, json=body, headers=mutation_headers()).status_code
        == 401
    )
    assert client(flow, signed_in=False).get(base("utility-baseline")).status_code == 401
    http = client(flow)
    no_csrf = mutation_headers()
    no_csrf.pop("X-CSRF-Token")
    assert http.post(path, json=body, headers=no_csrf).status_code == 403
    foreign = {**mutation_headers(), "Origin": "https://untrusted.example"}
    assert http.post(path, json=body, headers=foreign).status_code == 403
    no_key = mutation_headers()
    no_key.pop("Idempotency-Key")
    assert http.post(path, json=body, headers=no_key).status_code == 422
    assert flow.commands == []


def test_service_failures_map_to_status_and_stable_reason_codes() -> None:
    flow = MemoryFlow()
    http = client(flow)
    body = {"invoice_id": str(uuid4()), "consumption_period_id": str(uuid4())}
    path = base("utility-catch-up-invoice")
    cases: list[tuple[Exception, int, str]] = [
        (FinalUtilityInvoiceKeyReused("reused"), 409, "IDEMPOTENCY_KEY_REUSED"),
        (
            FinalUtilityInvoiceConflictError("conflict", "UTILITY_PERIOD_ALREADY_INVOICED"),
            409,
            "UTILITY_PERIOD_ALREADY_INVOICED",
        ),
        (FinalUtilityInvoiceConflictError("conflict"), 409, "CONFLICT"),
        (
            FinalUtilityInvoiceInvalidError("invalid", "UTILITY_UNRESOLVED_FINAL_INPUT"),
            422,
            "UTILITY_UNRESOLVED_FINAL_INPUT",
        ),
        (FinalUtilityInvoiceInvalidError("invalid"), 422, "VALIDATION_ERROR"),
        (MoveOutFinalInputsNotFoundError("missing"), 404, "NOT_FOUND"),
        (UtilityBaselineAuthorizationError("denied"), 403, "FORBIDDEN"),
        (RuntimeError("never leaked"), 500, ""),
    ]
    for failure, expected_status, code in cases:
        flow.failure = failure
        try:
            reply = http.post(path, json=body, headers=mutation_headers())
        except RuntimeError:
            assert expected_status == 500
            continue
        assert reply.status_code == expected_status, (failure, reply.text)
        if code:
            assert reply.json()["error"]["code"] == code
            assert "never leaked" not in reply.text
