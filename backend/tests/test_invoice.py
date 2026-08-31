"""Focused Invoice domain and protected API coverage for V1-045."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    MAX_INVOICE_EXPECTED_VERSION,
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
from property_rental.invoice_api import _version


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
    customer_id = uuid4()
    created_by = uuid4()
    first_line_id = uuid4()
    second_line_id = uuid4()
    return {
        "id": str(resolved_id),
        "invoice_number": f"INV-20260831-{resolved_id.hex[:12].upper()}",
        "property_id": str(property_id),
        "customer_id": str(customer_id),
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
                "id": str(first_line_id),
                "sequence": 1,
                "category": "MISCELLANEOUS_CHARGES",
                "description": "Authorized locksmith charge",
                "original_amount": {"currency": "USD", "minor_units": 10_000},
                "adjusted_amount": {"currency": "USD", "minor_units": 10_000},
                "outstanding_balance": {
                    "currency": "USD",
                    "minor_units": 0 if status in {"DRAFT", "VOID"} else 10_000,
                },
                "period": None,
                "source": {
                    "type": "AUTHORIZED_NONRECURRING_OBLIGATION",
                    "id": str(uuid4()),
                },
                "calculation_evidence": {
                    "formula": "authorized_source_exact_amount",
                    "authorized_amount_usd_cents": 10_000,
                },
                "created_at": "2026-08-31T01:02:03Z",
                "created_by": str(created_by),
            },
            {
                "id": str(second_line_id),
                "sequence": 2,
                "category": "MISCELLANEOUS_CHARGES",
                "description": "Authorized replacement key charge",
                "original_amount": {"currency": "USD", "minor_units": 2_500},
                "adjusted_amount": {"currency": "USD", "minor_units": 2_500},
                "outstanding_balance": {
                    "currency": "USD",
                    "minor_units": 0 if status in {"DRAFT", "VOID"} else 2_500,
                },
                "period": None,
                "source": {
                    "type": "AUTHORIZED_NONRECURRING_OBLIGATION",
                    "id": str(uuid4()),
                },
                "calculation_evidence": {
                    "formula": "authorized_source_exact_amount",
                    "authorized_amount_usd_cents": 2_500,
                },
                "created_at": "2026-08-31T01:02:03Z",
                "created_by": str(created_by),
            },
        ],
        "adjustments": [],
        "void_event": None,
        "issued_at": None,
        "issued_by": None,
        "created_at": "2026-08-31T01:02:03Z",
        "created_by": str(created_by),
        "updated_at": "2026-08-31T01:02:03Z",
        "updated_by": str(created_by),
        "version": version,
    }


@dataclass(slots=True)
class InMemoryInvoiceFlow:
    property_id: UUID
    value: dict[str, object]
    commands: list[object] = field(default_factory=list)
    replay_inputs: dict[tuple[str, UUID], object] = field(default_factory=dict)
    list_requests: list[dict[str, object]] = field(default_factory=list)
    property_lookups: int = 0

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
        del actor
        assert property_id == self.property_id
        self.list_requests.append(
            {
                "status_filter": status_filter,
                "category": category,
                "customer_id": customer_id,
                "lease_id": lease_id,
                "limit": limit,
                "cursor": cursor,
                "descending": descending,
            }
        )
        items = () if status_filter not in {None, self.value["status"]} else (self.value,)
        return InvoicePage(items, "stable-cursor" if items else None)

    def get(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        del actor
        assert invoice_id == UUID(str(self.value["id"]))
        return self.value

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        assert invoice_id == UUID(str(self.value["id"]))
        self.property_lookups += 1
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
    assert first != invoice_request_digest(
        action="adjust", property_id=uuid4(), invoice_id=invoice_id, payload=payload
    )
    assert first != invoice_request_digest(
        action="adjust", property_id=property_id, invoice_id=uuid4(), payload=payload
    )
    assert first != invoice_request_digest(
        action="adjust",
        property_id=property_id,
        invoice_id=invoice_id,
        payload={**payload, "reason": "Different correction"},
    )


def test_invoice_commands_reject_nil_ids_nonpositive_money_and_unnormalized_evidence() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        CreateInvoiceDraftCommand(UUID(int=0), uuid4())
    with pytest.raises(ValueError, match="positive integer"):
        AdjustInvoiceCommand(uuid4(), uuid4(), AdjustmentType.CREDIT, 0, "source", "reason", 1)
    with pytest.raises(ValueError, match="normalized"):
        VoidInvoiceCommand(uuid4(), " reason ", 1)


def test_invoice_command_versions_are_exact_positive_postgresql_integers() -> None:
    def commands(
        expected_version: int,
    ) -> tuple[
        CorrectInvoiceDraftCommand,
        IssueInvoiceCommand,
        AdjustInvoiceCommand,
        VoidInvoiceCommand,
    ]:
        return (
            CorrectInvoiceDraftCommand(uuid4(), uuid4(), "Correction", expected_version),
            IssueInvoiceCommand(uuid4(), expected_version),
            AdjustInvoiceCommand(
                uuid4(),
                uuid4(),
                AdjustmentType.CREDIT,
                1,
                "approved-correction/version-boundary",
                "Version boundary",
                expected_version,
            ),
            VoidInvoiceCommand(uuid4(), "Version boundary", expected_version),
        )

    assert all(
        command.expected_version == MAX_INVOICE_EXPECTED_VERSION
        for command in commands(MAX_INVOICE_EXPECTED_VERSION)
    )
    for invalid in (0, MAX_INVOICE_EXPECTED_VERSION + 1, True, cast(int, "1")):
        with pytest.raises(ValueError, match="expected_version"):
            commands(invalid)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("1", 1),
        ('"1"', 1),
        (" 000000001 ", 1),
        (str(MAX_INVOICE_EXPECTED_VERSION), MAX_INVOICE_EXPECTED_VERSION),
        (f'"{MAX_INVOICE_EXPECTED_VERSION}"', MAX_INVOICE_EXPECTED_VERSION),
    ],
)
def test_invoice_if_match_parser_preserves_bounded_decimal_grammar(
    header: str, expected: int
) -> None:
    assert _version(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        '""',
        "0",
        "-1",
        "+1",
        "1.0",
        "\N{ARABIC-INDIC DIGIT ONE}",
        "2147483648",
        "9" * 10_000,
    ],
)
def test_invoice_if_match_parser_rejects_unsafe_or_out_of_range_values(
    header: str | None,
) -> None:
    with pytest.raises(HTTPException) as rejected:
        _version(header)
    assert rejected.value.status_code == 412


def test_all_invoice_commands_bound_versions_before_flow_execution() -> None:
    property_id = uuid4()
    invoice_id = uuid4()
    source_id = uuid4()
    line_id = uuid4()
    all_capabilities = actor(
        property_id,
        "invoices.create",
        "invoices.issue",
        "invoices.adjust",
        "invoices.void",
    )
    cases: tuple[tuple[str, str, dict[str, object]], ...] = (
        (
            "PATCH",
            f"/api/v1/invoices/{invoice_id}",
            {
                "authorized_nonrecurring_obligation_id": str(source_id),
                "reason": "Version boundary correction",
            },
        ),
        ("POST", f"/api/v1/invoices/{invoice_id}/issue", {}),
        (
            "POST",
            f"/api/v1/invoices/{invoice_id}/adjustments",
            {
                "invoice_line_id": str(line_id),
                "adjustment_type": "CREDIT",
                "amount": {"currency": "USD", "minor_units": 1},
                "source_reference": "approved-correction/version-boundary",
                "reason": "Version boundary adjustment",
            },
        ),
        (
            "POST",
            f"/api/v1/invoices/{invoice_id}/void",
            {"reason": "Version boundary void"},
        ),
    )

    for method, path, payload in cases:
        flow = InMemoryInvoiceFlow(
            property_id,
            invoice_resource(
                property_id,
                invoice_id=invoice_id,
                version=MAX_INVOICE_EXPECTED_VERSION,
            ),
        )
        response = api(flow, all_capabilities).request(
            method,
            path,
            json=payload,
            headers={
                **mutation_headers(),
                "If-Match": f'"{MAX_INVOICE_EXPECTED_VERSION}"',
            },
        )
        assert response.status_code == 200
        assert len(flow.commands) == 1
        assert (
            cast(CorrectInvoiceDraftCommand, flow.commands[0]).expected_version
            == MAX_INVOICE_EXPECTED_VERSION
        )

    invalid_flow = InMemoryInvoiceFlow(
        property_id, invoice_resource(property_id, invoice_id=invoice_id)
    )
    invalid_client = api(invalid_flow, all_capabilities)
    for invalid_header in ('"2147483648"', "9" * 10_000):
        for method, path, payload in cases:
            response = invalid_client.request(
                method,
                path,
                json=payload,
                headers={**mutation_headers(), "If-Match": invalid_header},
            )
            assert response.status_code == 412
    assert invalid_flow.property_lookups == 0
    assert invalid_flow.commands == []


def test_create_accepts_only_authorized_source_and_enforces_scope_csrf_and_capability() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    allowed = api(flow, actor(property_id, "invoices.create"))
    source_id = uuid4()

    missing_csrf = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(source_id)},
        headers={"Idempotency-Key": str(uuid4())},
    )
    arbitrary_money = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={
            "authorized_nonrecurring_obligation_id": str(source_id),
            "amount_usd_cents": 1,
        },
        headers=mutation_headers(),
    )
    shortened_legacy_field = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )
    created = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )
    forbidden = api(flow, actor(property_id, "invoices.read")).post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )
    wrong_scope = api(flow, actor(uuid4(), "invoices.create")).post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(source_id)},
        headers=mutation_headers(),
    )

    assert missing_csrf.status_code == 403
    assert arbitrary_money.status_code == 422
    assert shortened_legacy_field.status_code == 422
    assert created.status_code == 201
    assert created.headers["location"].endswith(str(flow.value["id"]))
    assert created.headers["etag"] == '"1"'
    assert flow.commands[-1] == CreateInvoiceDraftCommand(
        UUID(created.request.headers["Idempotency-Key"]), source_id
    )
    assert forbidden.status_code == 403
    assert wrong_scope.status_code == 403

    nil_source = allowed.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(UUID(int=0))},
        headers=mutation_headers(),
    )
    assert nil_source.status_code == 422


def test_invoice_response_schema_is_complete_and_consistent_across_command_list_and_detail() -> (
    None
):
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.create", "invoices.read"))
    created = client.post(
        f"/api/v1/properties/{property_id}/invoices",
        json={"authorized_nonrecurring_obligation_id": str(uuid4())},
        headers=mutation_headers(),
    )
    detail = client.get(f"/api/v1/invoices/{flow.value['id']}")
    listed = client.get(f"/api/v1/properties/{property_id}/invoices")

    assert created.status_code == 201
    assert detail.status_code == 200
    assert listed.status_code == 200
    assert set(created.json()) == {"data", "meta"}
    assert set(detail.json()) == {"data", "meta"}
    assert set(listed.json()) == {"data", "page", "meta"}
    assert created.json()["data"] == detail.json()["data"] == listed.json()["data"][0]
    assert listed.json()["page"] == {"next_cursor": "stable-cursor", "limit": 50}
    for response in (created, detail, listed):
        assert set(response.json()["meta"]) == {"request_id"}
        UUID(response.json()["meta"]["request_id"])

    resource = created.json()["data"]
    assert set(resource) == {
        "id",
        "invoice_number",
        "property_id",
        "customer_id",
        "lease_id",
        "category",
        "status",
        "invoice_date",
        "due_date",
        "due_date_rule",
        "due_date_source",
        "property_timezone",
        "billing_period",
        "original_total",
        "adjusted_total",
        "active_application_total",
        "outstanding_balance",
        "lines",
        "adjustments",
        "void_event",
        "issued_at",
        "issued_by",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "version",
    }
    UUID(resource["customer_id"])
    assert resource["lease_id"] is None
    assert resource["category"] == "MISCELLANEOUS_CHARGES"
    assert resource["invoice_date"] == "2026-08-31"
    assert resource["due_date"] == "2026-09-15"
    assert resource["billing_period"] is None
    assert resource["status"] == "DRAFT"
    assert resource["version"] == 1
    assert resource["issued_at"] is None
    assert resource["issued_by"] is None
    for audit_key in ("created_at", "created_by", "updated_at", "updated_by"):
        assert resource[audit_key] is not None

    money_fields = (
        "original_total",
        "adjusted_total",
        "active_application_total",
        "outstanding_balance",
    )
    assert all(
        set(resource[field]) == {"currency", "minor_units"} and resource[field]["currency"] == "USD"
        for field in money_fields
    )
    lines = resource["lines"]
    assert [line["sequence"] for line in lines] == [1, 2]
    for line in lines:
        assert set(line) == {
            "id",
            "sequence",
            "category",
            "description",
            "original_amount",
            "adjusted_amount",
            "outstanding_balance",
            "period",
            "source",
            "calculation_evidence",
            "created_at",
            "created_by",
        }
        assert set(line["source"]) == {"type", "id"}
        assert line["source"]["type"] == "AUTHORIZED_NONRECURRING_OBLIGATION"
        UUID(line["source"]["id"])
        assert line["calculation_evidence"]["formula"] == "authorized_source_exact_amount"
        assert line["period"] is None
        for amount_field in ("original_amount", "adjusted_amount", "outstanding_balance"):
            assert set(line[amount_field]) == {"currency", "minor_units"}
            assert line[amount_field]["currency"] == "USD"


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
    customer_id = uuid4()
    lease_id = uuid4()

    page = client.get(
        f"/api/v1/properties/{property_id}/invoices",
        params={
            "status": "DRAFT",
            "category": "MISCELLANEOUS_CHARGES",
            "customer_id": str(customer_id),
            "lease_id": str(lease_id),
            "sort": "invoice_date",
            "limit": 1,
            "cursor": "opaque-input-cursor",
        },
    )
    unsupported = client.get(
        f"/api/v1/properties/{property_id}/invoices", params={"include": "customer"}
    )
    below_minimum = client.get(f"/api/v1/properties/{property_id}/invoices", params={"limit": 0})
    above_maximum = client.get(f"/api/v1/properties/{property_id}/invoices", params={"limit": 101})

    assert page.status_code == 200
    assert page.json()["page"] == {"next_cursor": "stable-cursor", "limit": 1}
    assert flow.list_requests == [
        {
            "status_filter": "DRAFT",
            "category": "MISCELLANEOUS_CHARGES",
            "customer_id": customer_id,
            "lease_id": lease_id,
            "limit": 1,
            "cursor": "opaque-input-cursor",
            "descending": False,
        }
    ]
    assert unsupported.status_code == 400
    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422


def test_draft_correction_requires_if_match_and_replays_exact_same_key() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.create"))
    invoice_id = flow.value["id"]
    source_id = uuid4()
    key = uuid4()
    payload = {
        "authorized_nonrecurring_obligation_id": str(source_id),
        "reason": "Correct source",
    }

    missing_key_headers = mutation_headers(version=1)
    del missing_key_headers["Idempotency-Key"]
    missing_key = client.patch(
        f"/api/v1/invoices/{invoice_id}", json=payload, headers=missing_key_headers
    )
    malformed_key = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json=payload,
        headers={**mutation_headers(version=1), "Idempotency-Key": ""},
    )
    non_uuid_key = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json=payload,
        headers={**mutation_headers(version=1), "Idempotency-Key": "not-a-uuid"},
    )
    nil_key = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json=payload,
        headers=mutation_headers(key=UUID(int=0), version=1),
    )

    shortened_legacy_field = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"authorized_obligation_id": str(source_id), "reason": "Correct source"},
        headers=mutation_headers(version=1),
    )

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
    changed_input = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={**payload, "reason": "Different source correction"},
        headers=mutation_headers(key=key, version=1),
    )

    assert missing_key.status_code == 422
    assert malformed_key.status_code == 422
    assert non_uuid_key.status_code == 422
    assert nil_key.status_code == 422
    assert shortened_legacy_field.status_code == 422
    assert missing.status_code == 412
    assert corrected.status_code == 200
    assert replay.status_code == 200
    assert corrected.json()["data"] == replay.json()["data"]
    assert changed_input.status_code == 409
    assert changed_input.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


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
    key = uuid4()
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
    non_integer_amount = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json={**payload, "amount": {"currency": "USD", "minor_units": 500.5}},
        headers=mutation_headers(version=2),
    )
    adjusted = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json=payload,
        headers=mutation_headers(key=key, version=2),
    )
    forbidden = api(flow, actor(property_id, "invoices.issue")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        json=payload,
        headers=mutation_headers(version=3),
    )

    assert invalid_currency.status_code == 422
    assert non_integer_amount.status_code == 422
    assert adjusted.status_code == 200
    assert flow.commands[-1] == AdjustInvoiceCommand(
        key,
        UUID(str(line_id)),
        AdjustmentType.CREDIT,
        500,
        "approved-correction/7",
        "Correct overcharge",
        2,
    )
    assert forbidden.status_code == 404


def test_void_is_explicit_versioned_terminal_command_with_separate_capability() -> None:
    property_id = uuid4()
    value = invoice_resource(property_id, status="UNPAID", version=2)
    flow = InMemoryInvoiceFlow(property_id, value)
    invoice_id = value["id"]
    void_key = uuid4()
    reason = "Obligation fundamentally invalid"

    forbidden = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/void",
        json={"reason": reason},
        headers=mutation_headers(version=2),
    )
    voided = api(flow, actor(property_id, "invoices.void")).post(
        f"/api/v1/invoices/{invoice_id}/void",
        json={"reason": reason},
        headers=mutation_headers(key=void_key, version=2),
    )
    stale = api(flow, actor(property_id, "invoices.void")).post(
        f"/api/v1/invoices/{invoice_id}/void",
        json={"reason": "Try again"},
        headers=mutation_headers(version=2),
    )

    assert forbidden.status_code == 404
    assert voided.status_code == 200
    assert flow.commands == [VoidInvoiceCommand(void_key, reason, 2)]
    assert voided.json()["data"]["status"] == "VOID"
    assert stale.status_code == 412
    assert stale.json()["error"]["current_version"] == 3
