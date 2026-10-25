"""Move-out cleaning charge and hand-back month routes (V1-056 slice 11a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.invoice import (
    InvoiceConflictError,
    InvoiceInvalidError,
    InvoiceVersionConflict,
    RecordUnitCleaningChargeCommand,
    ResolveHandBackRentCommand,
    SetUnitCleaningRateCommand,
)
from property_rental.invoice_api import REFUSALS_BY_DATABASE_MESSAGE
from test_invoice import actor, mutation_headers


class DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def refused(message: str, error: type[Exception] = InvoiceInvalidError) -> Exception:
    try:
        raise DatabaseRefusal(message)
    except DatabaseRefusal as cause:
        mapped = error("Invoice command is invalid")
        mapped.__cause__ = cause
        return mapped


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    invoice: UUID = field(default_factory=uuid4)
    rate: dict[str, object] | None = None
    error: Exception | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _answer(self, name: str, value: object, answer: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error
        return answer

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        assert invoice_id == self.invoice
        return self.prop

    def unit_cleaning_rate(
        self, property_id: UUID, unit_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object] | None:
        self.calls.append(("rate", (property_id, unit_id)))
        return self.rate

    def set_unit_cleaning_rate(
        self, property_id: UUID, command: SetUnitCleaningRateCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return self._answer("set_rate", command, {"id": str(command.rate_id)})

    def record_unit_cleaning_charge(
        self,
        property_id: UUID,
        command: RecordUnitCleaningChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._answer("charge", command, {"id": str(command.charge_id)})

    def hand_back_rent_assessment(
        self, property_id: UUID, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return self._answer(
            "assess", invoice_id, {"action": "VOID", "outstanding_usd_cents": 80_000}
        )

    def resolve_hand_back_rent(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: ResolveHandBackRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._answer(
            "resolve",
            command,
            {"invoice": {"id": str(invoice_id), "version": 3}, "action": command.expected_action},
        )


def api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, move_out_billing_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def rate_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "rate_id": str(uuid4()),
        "expected_current_rate_id": None,
        "rate_usd_cents": 2_500,
        "reason": "New cleaning price",
    }
    return {**body, **changes}


def test_the_cleaning_rate_is_read_by_the_charge_or_rate_form_only() -> None:
    flow = Flow(rate={"id": "rate-1", "rate_usd_cents": 2_500})
    unit = uuid4()
    url = f"/api/v1/properties/{flow.prop}/units/{unit}/cleaning-rate"
    for capability in ("invoices.create", "property.manage"):
        answer = api(flow, actor(flow.prop, capability)).get(url)
        assert answer.status_code == 200
        assert answer.json()["data"] == {
            "property_id": str(flow.prop),
            "unit_id": str(unit),
            "rate": {"id": "rate-1", "rate_usd_cents": 2_500},
        }
        assert answer.headers["cache-control"] == "private, no-store"
    flow.rate = None
    assert api(flow, actor(flow.prop, "invoices.create")).get(url).json()["data"]["rate"] is None
    assert api(flow, actor(flow.prop, "invoices.read")).get(url).status_code == 403
    assert api(flow, actor(uuid4(), "property.manage")).get(url).status_code == 403
    assert api(flow, None).get(url).status_code == 401
    assert api(flow, actor(flow.prop, "invoices.create")).get(url + "?x=1").status_code == 400


def test_property_manage_sets_a_unit_cleaning_rate_with_csrf() -> None:
    flow = Flow()
    unit = uuid4()
    url = f"/api/v1/properties/{flow.prop}/units/{unit}/cleaning-rates"
    manager = api(flow, actor(flow.prop, "property.manage"))
    body = rate_body(rate_usd_cents=0)
    created = manager.post(url, json=body, headers=mutation_headers())
    assert created.status_code == 201
    command = flow.calls[-1][1]
    assert isinstance(command, SetUnitCleaningRateCommand)
    assert (command.unit_id, command.rate_usd_cents, command.expected_current_rate_id) == (
        unit,
        0,
        None,
    )
    flow.calls.clear()
    denied = api(flow, actor(flow.prop, "invoices.create", "settings.manage"))
    assert denied.post(url, json=rate_body(), headers=mutation_headers()).status_code == 403
    no_csrf = {"Origin": "https://localhost"}
    assert manager.post(url, json=rate_body(), headers=no_csrf).status_code == 403
    # The expected current rate is required, so a form cannot skip the check.
    missing = {
        key: value for key, value in rate_body().items() if key != "expected_current_rate_id"
    }
    assert manager.post(url, json=missing, headers=mutation_headers()).status_code == 422
    assert (
        manager.post(url, json=rate_body(rate_usd_cents=-1), headers=mutation_headers()).status_code
        == 422
    )
    assert (
        manager.post(
            url, json=rate_body(rate_usd_cents="25"), headers=mutation_headers()
        ).status_code
        == 422
    )
    assert flow.calls == []
    flow.error = refused("Unit cleaning rate changed", InvoiceConflictError)
    changed = manager.post(url, json=rate_body(), headers=mutation_headers())
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "CLEANING_RATE_CHANGED"


def test_invoices_create_records_the_cleaning_charge_from_the_rate_shown() -> None:
    flow = Flow()
    lease, rate, charge = uuid4(), uuid4(), uuid4()
    url = f"/api/v1/properties/{flow.prop}/leases/{lease}/cleaning-charge"
    body = {"charge_id": str(charge), "expected_rate_id": str(rate)}
    recorded = api(flow, actor(flow.prop, "invoices.create")).post(
        url, json=body, headers=mutation_headers()
    )
    assert recorded.status_code == 201
    assert flow.calls == [("charge", RecordUnitCleaningChargeCommand(charge, lease, rate))]
    assert (
        api(flow, actor(flow.prop, "property.manage"))
        .post(url, json=body, headers=mutation_headers())
        .status_code
        == 403
    )
    assert (
        api(flow, actor(flow.prop, "invoices.create"))
        .post(url, json={**body, "amount_usd_cents": 1}, headers=mutation_headers())
        .status_code
        == 422
    )


@pytest.mark.parametrize("message", sorted(REFUSALS_BY_DATABASE_MESSAGE))
def test_each_business_state_refusal_answers_its_own_code(message: str) -> None:
    flow = Flow(error=refused(message))
    refusal = REFUSALS_BY_DATABASE_MESSAGE[message]
    who = actor(flow.prop, "invoices.create", "invoices.read", "leases.read", "invoices.void")
    client = api(flow, who)
    answers = [
        client.post(
            f"/api/v1/properties/{flow.prop}/leases/{uuid4()}/cleaning-charge",
            json={"charge_id": str(uuid4()), "expected_rate_id": str(uuid4())},
            headers=mutation_headers(),
        ),
        client.get(f"/api/v1/invoices/{flow.invoice}/hand-back-assessment"),
        client.post(
            f"/api/v1/invoices/{flow.invoice}/hand-back-resolution",
            json={
                "action": "VOID",
                "expected_outstanding_usd_cents": 80_000,
                "reason": "Before 5th",
            },
            headers=mutation_headers(version=2),
        ),
    ]
    for answer in answers:
        assert answer.status_code == refusal.status_code == 409
        assert answer.json()["error"]["code"] == refusal.code
        assert message not in answer.text


def test_an_unnamed_database_refusal_stays_a_plain_answer_without_its_text() -> None:
    flow = Flow(error=refused("Unit cleaning charge is invalid"))
    answer = api(flow, actor(flow.prop, "invoices.create")).post(
        f"/api/v1/properties/{flow.prop}/leases/{uuid4()}/cleaning-charge",
        json={"charge_id": str(uuid4()), "expected_rate_id": str(uuid4())},
        headers=mutation_headers(),
    )
    assert answer.status_code == 422
    assert "Unit cleaning charge" not in answer.text
    flow.error = InvoiceConflictError("Invoice command conflicted")
    plain = api(flow, actor(flow.prop, "invoices.create")).post(
        f"/api/v1/properties/{flow.prop}/leases/{uuid4()}/cleaning-charge",
        json={"charge_id": str(uuid4()), "expected_rate_id": str(uuid4())},
        headers=mutation_headers(),
    )
    assert plain.status_code == 409
    assert plain.json()["error"]["code"] == "CONFLICT"


def test_the_hand_back_assessment_needs_invoice_and_lease_reads() -> None:
    flow = Flow()
    url = f"/api/v1/invoices/{flow.invoice}/hand-back-assessment"
    both = api(flow, actor(flow.prop, "invoices.read", "leases.read")).get(url)
    assert both.status_code == 200
    assert both.json()["data"] == {"action": "VOID", "outstanding_usd_cents": 80_000}
    for capability in ("invoices.read", "leases.read"):
        assert api(flow, actor(flow.prop, capability)).get(url).status_code == 404
    assert api(flow, None).get(url).status_code == 401


def test_the_hand_back_action_needs_its_own_capability_a_version_and_a_key() -> None:
    flow = Flow()
    url = f"/api/v1/invoices/{flow.invoice}/hand-back-resolution"
    void = {"action": "VOID", "expected_outstanding_usd_cents": 80_000, "reason": "Before the 5th"}
    credit = {**void, "action": "CREDIT_ADJUSTMENT", "expected_outstanding_usd_cents": 30_000}
    voider = api(flow, actor(flow.prop, "invoices.void"))
    adjuster = api(flow, actor(flow.prop, "invoices.adjust"))
    assert voider.post(url, json=credit, headers=mutation_headers(version=2)).status_code == 404
    assert adjuster.post(url, json=void, headers=mutation_headers(version=2)).status_code == 404
    assert voider.post(url, json=void, headers=mutation_headers()).status_code == 412
    no_key = {
        key: value for key, value in mutation_headers(version=2).items() if key != "Idempotency-Key"
    }
    assert voider.post(url, json=void, headers=no_key).status_code == 422
    assert flow.calls == []
    done = voider.post(url, json=void, headers=mutation_headers(version=2))
    assert done.status_code == 200
    assert done.headers["etag"] == '"3"'
    command = flow.calls[-1][1]
    assert isinstance(command, ResolveHandBackRentCommand)
    assert (command.expected_action, command.expected_version) == ("VOID", 2)
    assert command.expected_outstanding_usd_cents == 80_000
    adjusted = adjuster.post(url, json=credit, headers=mutation_headers(version=3))
    assert adjusted.status_code == 200
    # The person who confirmed the action is the one the screen named.
    other = {**mutation_headers(version=3), "X-Billing-Actor-ID": str(uuid4())}
    assert adjuster.post(url, json=credit, headers=other).status_code == 403
    flow.error = InvoiceVersionConflict(4)
    stale = adjuster.post(url, json=credit, headers=mutation_headers(version=3))
    assert stale.status_code == 412
