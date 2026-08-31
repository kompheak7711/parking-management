"""Focused Invoice domain and protected API coverage for V1-045."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    InvoiceIdempotencyKeyReused,
    InvoicePage,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    VoidInvoiceCommand,
    invoice_request_digest,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def invoice_resource(
    property_id: UUID,
    *,
    invoice_id: UUID | None = None,
    status: str = "DRAFT",
    version: int = 1,
) -> dict[str, object]:
    resolved_id = invoice_id or uuid4()
    line_id = uuid4()
    return {
        "id": str(resolved_id),
        "invoice_number": f"INV-20260831-{resolved_id.hex[:12].upper()}",
        "property_id": str(property_id),
        "customer_id": str(uuid4()),
        "lease_id": None,
        "category": "MISCELLANEOUS_CHARGES",
        "status": status,
        "invoice_date": "2026-08-31",
        "due_date": "2026-09-15",
        "due_date_rule": "GOVERNING_SOURCE",
        "due_date_source": "approved-document/1",
        "property_timezone": "Asia/Phnom_Penh",
        "billing_period": None,
        "original_total": {"currency": "USD", "minor_units": 12_500},
        "adjusted_total": {"currency": "USD", "minor_units": 12_500},
        "active_application_total": {"currency": "USD", "minor_units": 0},
        "outstanding_balance": {
            "currency": "USD",
            "minor_units": 0 if status in {"DRAFT", "VOID"} else 12_500,
        },
        "lines": [
            {
                "id": str(line_id),
                "sequence": 1,
                "category": "MISCELLANEOUS_CHARGES",
                "source": {
                    "type": "AUTHORIZED_NONRECURRING_OBLIGATION",
                    "id": str(uuid4()),
                },
            }
        ],
        "adjustments": [],
        "void_event": None,
        "version": version,
    }


@dataclass(slots=True)
class InMemoryInvoiceFlow:
    property_id: UUID
    value: dict[str, object]
    commands: list[object] = field(default_factory=list)
    replay_inputs: dict[tuple[str, UUID], object] = field(default_factory=dict)

    def list(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        status_filter: str | None,
        category: str | None,
        customer_id: UUID | None,
        lease_id: UUID | None,
        limit: int,
        cursor: str | None,
        descending: bool,
    ) -> InvoicePage:
        del actor, category, customer_id, lease_id, limit, cursor, descending
        assert property_id == self.property_id
        items = () if status_filter not in {None, self.value["status"]} else (self.value,)
        return InvoicePage(items, "stable-cursor" if items else None)

    def get(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        del actor
        assert invoice_id == UUID(str(self.value["id"]))
        return self.value

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        assert invoice_id == UUID(str(self.value["id"]))
        return self.property_id

    def _replay(self, action: str, key: UUID, command: object) -> bool:
        identity = (action, key)
        prior = self.replay_inputs.get(identity)
        if prior is not None and prior != command:
            raise InvoiceIdempotencyKeyReused
        self.replay_inputs[identity] = command
        if prior is not None:
            return True
        self.commands.append(command)
        return False

    def create_draft(
        self,
        property_id: UUID,
        command: CreateInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        assert property_id == self.property_id
        self._replay("create", command.idempotency_key, command)
        return self.value

    def correct_draft(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: CorrectInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, invoice_id, actor
        replayed = self._replay("correct", command.idempotency_key, command)
        if replayed:
            return self.value
        if command.expected_version != int(str(self.value["version"])):
            raise InvoiceVersionConflict(int(str(self.value["version"])))
        self.value = {**self.value, "version": command.expected_version + 1}
        return self.value

    def issue(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: IssueInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, invoice_id, actor
        if command.expected_version != int(str(self.value["version"])):
            raise InvoiceVersionConflict(int(str(self.value["version"])))
        if not self._replay("issue", command.idempotency_key, command):
            self.value = {
                **self.value,
                "status": "UNPAID",
                "version": command.expected_version + 1,
            }
        return self.value

    def adjust(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: AdjustInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, invoice_id, actor
        if command.expected_version != int(str(self.value["version"])):
            raise InvoiceVersionConflict(int(str(self.value["version"])))
        if not self._replay("adjust", command.idempotency_key, command):
            self.value = {**self.value, "version": command.expected_version + 1}
        return self.value

    def void(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: VoidInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del property_id, invoice_id, actor
        if command.expected_version != int(str(self.value["version"])):
            raise InvoiceVersionConflict(int(str(self.value["version"])))
        if not self._replay("void", command.idempotency_key, command):
            self.value = {
                **self.value,
                "status": "VOID",
                "version": command.expected_version + 1,
            }
        return self.value


def api(flow: InMemoryInvoiceFlow, authenticated: AuthenticatedActor) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: authenticated, invoice_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def mutation_headers(*, key: UUID | None = None, version: int | None = None) -> dict[str, str]:
    headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(key or uuid4()),
    }
    if version is not None:
        headers["If-Match"] = f'"{version}"'
    return headers


def test_invoice_digest_is_canonical_and_binds_action_scope_and_input() -> None:
    property_id = uuid4()
    invoice_id = uuid4()
    payload: dict[str, object] = {
        "amount": {"minor_units": 125, "currency": "USD"},
        "reason": "Correction",
    }

    first = invoice_request_digest(
        action="adjust", property_id=property_id, invoice_id=invoice_id, payload=payload
    )

    assert len(first) == 64
    assert first == invoice_request_digest(
        action="adjust",
        property_id=property_id,
        invoice_id=invoice_id,
        payload={"reason": "Correction", "amount": {"currency": "USD", "minor_units": 125}},
    )
    assert first != invoice_request_digest(
        action="void", property_id=property_id, invoice_id=invoice_id, payload=payload
    )


def test_invoice_commands_reject_nil_ids_nonpositive_money_and_unnormalized_evidence() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        CreateInvoiceDraftCommand(UUID(int=0), uuid4())
    with pytest.raises(ValueError, match="positive integer"):
        AdjustInvoiceCommand(uuid4(), uuid4(), AdjustmentType.CREDIT, 0, "source", "reason", 1)
    with pytest.raises(ValueError, match="normalized"):
        VoidInvoiceCommand(uuid4(), " reason ", 1)


def test_create_accepts_only_authorized_source_and_enforces_scope_csrf_and_capability() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    allowed = api(flow, actor(property_id, "invoices.create"))
    source_id = uuid4()

    missing_csrf = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id)},
        headers={"Idempotency-Key": str(uuid4())},
    )
    arbitrary_money = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id), "amount_usd_cents": 1},
        headers=mutation_headers(),
    )
    created = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )
    forbidden = api(flow, actor(property_id, "invoices.read")).post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )
    wrong_scope = api(flow, actor(uuid4(), "invoices.create")).post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )

    assert missing_csrf.status_code == 403
    assert arbitrary_money.status_code == 422
    assert created.status_code == 201
    assert created.headers["location"].endswith(str(flow.value["id"]))
    assert created.headers["etag"] == '"1"'
    assert forbidden.status_code == 403
    assert wrong_scope.status_code == 403

    nil_source = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(UUID(int=0))},
        headers=mutation_headers(),
    )
    assert nil_source.status_code == 422


def test_detail_hides_invoice_without_exact_read_scope() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    invoice_id = flow.value["id"]

    visible = api(flow, actor(property_id, "invoices.read")).get(f"/api/v1/invoices/{invoice_id}")
    hidden = api(flow, actor(property_id, "invoices.create")).get(f"/api/v1/invoices/{invoice_id}")

    assert visible.status_code == 200
    assert visible.json()["data"]["customer_id"] == flow.value["customer_id"]
    assert hidden.status_code == 404


def test_list_has_allowlisted_filters_and_stable_cursor_envelope() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.read"))

    page = client.get(
        f"/api/v1/properties/{property_id}/invoices",
        params={
            "status": "DRAFT",
            "lease_id": str(uuid4()),
            "sort": "-invoice_date",
            "limit": 1,
        },
    )
    unsupported = client.get(
        f"/api/v1/properties/{property_id}/invoices", params={"include": "customer"}
    )

    assert page.status_code == 200
    assert page.json()["page"] == {"next_cursor": "stable-cursor", "limit": 1}
    assert unsupported.status_code == 400


def test_draft_correction_requires_if_match_and_replays_exact_same_key() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.create"))
    invoice_id = flow.value["id"]
    source_id = uuid4()
    key = uuid4()
    payload = {"authorized_obligation_id": str(source_id), "reason": "Correct source"}

    missing = client.patch(
        f"/api/v1/invoices/{invoice_id}", json=payload, headers=mutation_headers(key=key)
    )
    corrected = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json=payload,
        headers=mutation_headers(key=key, version=1),
    )
    replay = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json=payload,
        headers=mutation_headers(key=key, version=1),
    )

    assert missing.status_code == 412
    assert corrected.status_code == 200
    assert replay.status_code == 200
    assert corrected.json()["data"] == replay.json()["data"]


def test_issue_uses_separate_capability_and_only_client_version_changes() -> None:
    property_id = uuid4()
    invoice_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id, invoice_id=invoice_id))
    key = uuid4()

    forbidden = api(flow, actor(property_id, "invoices.create")).post(
        f"/api/v1/invoices/{invoice_id}/issue",
        json={},
        headers=mutation_headers(key=key, version=1),
    )
    issued = api(flow, actor(property_id, "invoices.issue")).post(
        f"/api/v1/invoices/{invoice_id}/issue",
        json={},
        headers=mutation_headers(key=key, version=1),
    )

    assert forbidden.status_code == 404
    assert issued.status_code == 200
    assert issued.json()["data"]["status"] == "UNPAID"
    assert issued.headers["etag"] == '"2"'


def test_adjustment_requires_exact_usd_integer_reason_source_and_capability() -> None:
    property_id = uuid4()
    value = invoice_resource(property_id, status="UNPAID", version=2)
    flow = InMemoryInvoiceFlow(property_id, value)
    invoice_id = value["id"]
    line_id = value["lines"][0]["id"]  # type: ignore[index]
    payload = {
        "invoice_line_id": line_id,
        "adjustment_type": "CREDIT",
        "amount": {"currency": "USD", "minor_units": 500},
        "source_reference": "approved-correction/7",
        "reason": "Correct overcharge",
    }

    invalid_currency = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json={**payload, "amount": {"currency": "KHR", "minor_units": 500}},
        headers=mutation_headers(version=2),
    )
    adjusted = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json=payload,
        headers=mutation_headers(version=2),
    )
    forbidden = api(flow, actor(property_id, "invoices.issue")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json=payload,
        headers=mutation_headers(version=3),
    )

    assert invalid_currency.status_code == 422
    assert adjusted.status_code == 200
    assert isinstance(flow.commands[-1], AdjustInvoiceCommand)
    assert forbidden.status_code == 404


def test_void_is_explicit_versioned_terminal_command_with_separate_capability() -> None:
    property_id = uuid4()
    value = invoice_resource(property_id, status="UNPAID", version=2)
    flow = InMemoryInvoiceFlow(property_id, value)
    invoice_id = value["id"]

    voided = api(flow, actor(property_id, "invoices.void")).post(
        f"/api/v1/invoices/{invoice_id}/void",
        json={"reason": "Obligation fundamentally invalid"},
        headers=mutation_headers(version=2),
    )
    stale = api(flow, actor(property_id, "invoices.void")).post(
        f"/api/v1/invoices/{invoice_id}/void",
        json={"reason": "Try again"},
        headers=mutation_headers(version=2),
    )

    assert voided.status_code == 200
    assert voided.json()["data"]["status"] == "VOID"
    assert stale.status_code == 412
    assert stale.json()["error"]["current_version"] == 3
