"""Property-scoped staff billing visibility; commands retain their own authorization."""

from typing import cast
from uuid import UUID, uuid4

from property_rental.billing import SetInitialRentDueDateCommand
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import (
    CreateItemsInvoiceDraftCommand,
    CreateServicesInvoiceDraftCommand,
    InvoiceItem,
    InvoiceLineFullyPaid,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
    ReplaceInvoiceDraftItemsCommand,
    ServiceInvoiceItem,
    SetOneTimeChargeDueDaysCommand,
)
from test_invoice import InMemoryInvoiceFlow, actor, api, invoice_resource, mutation_headers


def test_billing_action_metadata_denies_by_default_and_uses_exact_property() -> None:
    property_id = uuid4()
    other_property = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    reader = actor(property_id, "invoices.read")
    read_only = api(flow, reader).get(f"/api/v1/properties/{property_id}/invoices")
    assert read_only.status_code == 200
    assert read_only.json()["meta"]["billing_capabilities"] == []
    mixed = AuthenticatedActor(
        actor_id=reader.actor_id,
        capability_grants=reader.capability_grants
        | frozenset(
            {
                CapabilityGrant("invoices.issue", frozenset({str(property_id)})),
                CapabilityGrant("invoices.void", frozenset({str(other_property)})),
                CapabilityGrant("late_payment.final_decision", frozenset({str(property_id)})),
            }
        ),
    )
    scoped = api(flow, mixed).get(f"/api/v1/properties/{property_id}/invoices")
    assert scoped.json()["meta"]["billing_capabilities"] == [
        "invoices.issue",
        "late_payment.final_decision",
    ]
    assert api(flow, None).get(f"/api/v1/properties/{property_id}/invoices").status_code == 401
    assert (
        api(flow, actor(other_property, "invoices.read"))
        .get(f"/api/v1/properties/{property_id}/invoices")
        .status_code
        == 403
    )


def test_billing_visibility_lists_damage_billing_property_management_and_settings_access() -> None:
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    visibility = api(
        flow, actor(property_id, "damage_charges.bill", "property.manage", "settings.manage")
    ).get(f"/api/v1/properties/{property_id}/billing-capabilities")
    # Login sub-slice L5: `settings.manage` shows the one-time charge due days form.
    assert visibility.json()["data"]["billing_capabilities"] == [
        "damage_charges.bill",
        "property.manage",
        "settings.manage",
    ]


def test_independent_billing_visibility_does_not_require_invoice_read() -> None:
    property_id, other = uuid4(), uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    generator = actor(property_id, "billing.generate")
    client = api(flow, generator)
    visibility = client.get(f"/api/v1/properties/{property_id}/billing-capabilities")
    assert visibility.status_code == 200
    assert visibility.json()["data"] == {
        "property_id": str(property_id),
        "billing_capabilities": ["billing.generate"],
    }
    assert client.get(f"/api/v1/properties/{property_id}/invoices").status_code == 403
    assert (
        client.get(f"/api/v1/properties/{other}/billing-capabilities").json()["data"][
            "billing_capabilities"
        ]
        == []
    )
    assert (
        api(flow, None).get(f"/api/v1/properties/{property_id}/billing-capabilities").status_code
        == 401
    )
    assert "no-store" in visibility.headers["cache-control"]


def test_all_invoice_mutations_bind_the_confirming_actor_before_service_dispatch() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    current = actor(
        property_id, "invoices.create", "invoices.issue", "invoices.adjust", "invoices.void"
    )
    client = api(flow, current)
    headers = {**mutation_headers(version=1), "X-Billing-Actor-ID": str(uuid4())}
    invoice_id = str(flow.value["id"])
    cases: list[tuple[str, str, dict[str, object]]] = [
        (
            "POST",
            f"/properties/{property_id}/invoices",
            {"authorized_nonrecurring_obligation_id": str(uuid4())},
        ),
        (
            "PATCH",
            f"/invoices/{invoice_id}",
            {"authorized_nonrecurring_obligation_id": str(uuid4()), "reason": "Correction"},
        ),
        ("POST", f"/properties/{property_id}/invoices/drafts", _items_body()),
        ("POST", f"/properties/{property_id}/invoices/services-drafts", _services_body()),
        (
            "PUT",
            f"/invoices/{invoice_id}/items",
            {**_items_body(), "change_reason": "Customer asked for one more key"},
        ),
        ("POST", f"/invoices/{invoice_id}/issue", {}),
        ("POST", f"/invoices/{invoice_id}/void", {"reason": "Invalid source"}),
        (
            "POST",
            f"/invoices/{invoice_id}/adjustments",
            {
                "invoice_line_id": str(uuid4()),
                "adjustment_type": "CREDIT",
                "amount": {"currency": "USD", "minor_units": 100},
                "source_reference": "approved",
                "reason": "Correction",
            },
        ),
    ]
    for method, path, body in cases:
        response = client.request(method, "/api/v1" + path, headers=headers, json=body)
        assert response.status_code == 403
    assert flow.commands == []
    assert flow.property_lookups == 0
    headers["X-Billing-Actor-ID"] = current.actor_id
    assert (
        client.post(
            f"/api/v1/invoices/{invoice_id}/void",
            headers=headers,
            json={"reason": "Invalid source"},
        ).status_code
        == 200
    )
    assert flow.value["status"] == "VOID"


def test_exact_version_rejection_has_safe_current_version_and_correlation() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id, version=3))
    current = actor(property_id, "invoices.issue")
    client = api(flow, current)
    result = client.post(
        f"/api/v1/invoices/{flow.value['id']}/issue",
        json={},
        headers={**mutation_headers(version=2), "X-Billing-Actor-ID": current.actor_id},
    )
    assert result.status_code == 412
    assert result.json()["error"]["code"] == "PRECONDITION_FAILED"
    assert result.json()["error"]["current_version"] == 3
    assert result.json()["meta"]["request_id"]
    assert flow.value["status"] == "DRAFT"


def test_invoice_validation_retains_safe_field_locations_and_request_id() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.void"))
    result = client.post(
        f"/api/v1/invoices/{flow.value['id']}/void",
        json={"reason": ""},
        headers={**mutation_headers(version=1), "X-Request-ID": "billing-review-123"},
    )
    assert result.status_code == 422
    assert result.json()["error"]["fields"] == ["body.reason"]
    assert result.json()["meta"]["request_id"] == "billing-review-123"


def test_issue_route_passes_an_authorized_due_date_override_with_its_reason() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    client = api(flow, actor(property_id, "invoices.issue"))
    invoice_id = str(flow.value["id"])
    headers = mutation_headers(version=1)
    only_date = client.post(
        f"/api/v1/invoices/{invoice_id}/issue", headers=headers, json={"due_date": "2026-10-20"}
    )
    assert only_date.status_code == 422
    ok = client.post(
        f"/api/v1/invoices/{invoice_id}/issue",
        headers=headers,
        json={"due_date": "2026-10-20", "due_date_reason": "Owner agreed a later date"},
    )
    assert ok.status_code == 200
    command = cast(IssueInvoiceCommand, flow.commands[-1])
    assert str(command.due_date) == "2026-10-20"
    assert command.due_date_reason == "Owner agreed a later date"


def test_one_time_charge_route_needs_the_category_capability_and_validates_the_body() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    body = {
        "charge_id": str(uuid4()),
        "category": "MISCELLANEOUS_CHARGES",
        "customer_id": str(uuid4()),
        "description": "Key replacement",
        "amount_usd_cents": 1500,
        "reason": "Lost key",
        "evidence_reference": "Receipt 12",
    }
    path = f"/api/v1/properties/{property_id}/one-time-charges"
    denied = api(flow, actor(property_id, "invoices.issue")).post(
        path, headers=mutation_headers(), json=body
    )
    assert denied.status_code == 403 and flow.commands == []
    client = api(flow, actor(property_id, "invoices.create"))
    for bad in ({**body, "amount_usd_cents": 12.5}, {**body, "amount_usd_cents": 0}):
        assert client.post(path, headers=mutation_headers(), json=bad).status_code == 422
    created = client.post(path, headers=mutation_headers(), json=body)
    assert created.status_code == 201
    assert cast(RecordOneTimeChargeCommand, flow.commands[-1]).amount_usd_cents == 1500
    assert created.headers["cache-control"] == "private, no-store"
    damage = {**body, "category": "DAMAGE_CHARGES"}
    assert client.post(path, headers=mutation_headers(), json=damage).status_code == 403


def test_one_time_charge_due_days_route_needs_settings_access_and_the_exact_version() -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): the due days are a Settings
    item, so `property.manage` no longer changes them."""
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    path = f"/api/v1/properties/{property_id}/one-time-charge-due-days"
    body = {"days": 10, "reason": "Owner changed the policy"}
    for capability in ("invoices.issue", "property.manage"):
        denied = api(flow, actor(property_id, capability)).post(
            path, headers=mutation_headers(version=3), json=body
        )
        assert denied.status_code == 403
    assert flow.commands == []
    client = api(flow, actor(property_id, "settings.manage"))
    assert client.post(path, headers=mutation_headers(), json=body).status_code == 412
    assert (
        client.post(
            path, headers=mutation_headers(version=3), json={**body, "days": 91}
        ).status_code
        == 422
    )
    ok = client.post(path, headers=mutation_headers(version=3), json=body)
    assert ok.status_code == 200
    assert cast(SetOneTimeChargeDueDaysCommand, flow.commands[-1]).days == 10
    assert cast(SetOneTimeChargeDueDaysCommand, flow.commands[-1]).expected_version == 3


def test_one_time_charge_due_days_read_needs_settings_access() -> None:
    """V1-058 R7b-4: the Settings Business tab reads the days and the version to change them."""
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    path = f"/api/v1/properties/{property_id}/one-time-charge-due-days"
    for capability in ("invoices.issue", "property.manage"):
        assert api(flow, actor(property_id, capability)).get(path).status_code == 403
    client = api(flow, actor(property_id, "settings.manage"))
    assert client.get(path + "?x=1").status_code == 400
    read = client.get(path)
    assert read.status_code == 200
    assert read.json()["data"] == {
        "property_id": str(property_id),
        "one_time_charge_due_days": 7,
        "version": 3,
    }


def test_initial_rent_due_date_route_uses_invoices_issue_with_a_mandatory_reason() -> None:
    from test_invoice import mutation_headers

    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    lease = uuid4()
    path = f"/api/v1/properties/{property_id}/leases/{lease}/initial-rent-due-date"
    body = {"override_id": str(uuid4()), "due_date": "2026-10-20", "reason": "Owner agreed"}
    denied = api(flow, actor(property_id, "invoices.create")).post(
        path, headers=mutation_headers(), json=body
    )
    assert denied.status_code == 403 and flow.commands == []
    client = api(flow, actor(property_id, "invoices.issue"))
    assert (
        client.post(path, headers=mutation_headers(), json={**body, "reason": ""}).status_code
        == 422
    )
    assert (
        client.post(path, headers=mutation_headers(), json={**body, "due_date": "soon"}).status_code
        == 422
    )
    assert client.post(path, headers=mutation_headers(), json=body).status_code == 200
    command = cast(SetInitialRentDueDateCommand, flow.commands[-1])
    assert (command.lease_id, command.due_date.isoformat()) == (lease, "2026-10-20")


def test_debit_adjustment_on_a_fully_paid_line_answers_a_stable_conflict_code() -> None:
    property_id, invoice_id, line_id = uuid4(), uuid4(), uuid4()

    class FullyPaid(InMemoryInvoiceFlow):
        def adjust(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise InvoiceLineFullyPaid(0)

    flow = FullyPaid(property_id, invoice_resource(property_id, invoice_id=invoice_id))
    reply = api(flow, actor(property_id, "invoices.adjust")).post(
        f"/api/v1/invoices/{invoice_id}/adjustments",
        headers=mutation_headers(version=2),
        json={
            "invoice_line_id": str(line_id),
            "adjustment_type": "DEBIT",
            "amount": {"currency": "USD", "minor_units": 100},
            "source_reference": "approved-correction/missed-amount",
            "reason": "Missed amount",
        },
    )
    assert reply.status_code == 409
    error = reply.json()["error"]
    assert error["code"] == "INVOICE_LINE_FULLY_PAID" and error["rule_ids"] == ["BR-INV-044"]
    assert "balance" in error["message"]


def _items_body() -> dict[str, object]:
    return {
        "customer_id": str(uuid4()),
        "lease_id": None,
        "reason": "Keys and a lock",
        "evidence_reference": "Receipt 12",
        "items": [
            {
                "charge_id": str(uuid4()),
                "description": "Key copy",
                "quantity": 2,
                "unit_price_usd_cents": 1500,
            },
            {
                "charge_id": str(uuid4()),
                "description": "Door lock",
                "quantity": 1,
                "unit_price_usd_cents": 3999,
            },
        ],
    }


def _services_body() -> dict[str, object]:
    return {
        "customer_id": str(uuid4()),
        "lease_id": None,
        "items": [
            {"charge_id": str(uuid4()), "regular_service_id": str(uuid4()), "quantity": 3},
            {"charge_id": str(uuid4()), "regular_service_id": str(uuid4()), "quantity": 1},
        ],
    }


def test_services_invoice_route_takes_no_price_and_needs_invoices_create() -> None:
    """DL-115 (I): staff pick Regular services and How many; the price comes from Settings."""
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    path = f"/api/v1/properties/{property_id}/invoices/services-drafts"
    body = _services_body()
    items = cast(list[dict[str, object]], body["items"])
    denied = api(flow, actor(property_id, "invoices.issue")).post(
        path, headers=mutation_headers(), json=body
    )
    assert denied.status_code == 403 and flow.commands == []
    client = api(flow, actor(property_id, "invoices.create"))
    item = items[0]
    for bad in (
        {**body, "items": []},
        {**body, "items": [item, item]},
        {**body, "items": [item, {**item, "charge_id": str(uuid4())}]},
        {**body, "items": [{**item, "quantity": 0}]},
        {**body, "items": [{**item, "quantity": "2"}]},
        {**body, "items": [{**item, "unit_price_usd_cents": 100}]},
        {**body, "reason": "typed"},
    ):
        assert client.post(path, headers=mutation_headers(), json=bad).status_code == 422
    assert flow.commands == []
    created = client.post(path, headers=mutation_headers(), json=body)
    assert created.status_code == 201
    command = cast(CreateServicesInvoiceDraftCommand, flow.commands[-1])
    assert command.items == tuple(
        ServiceInvoiceItem(
            UUID(str(value["charge_id"])),
            UUID(str(value["regular_service_id"])),
            cast(int, value["quantity"]),
        )
        for value in items
    )


def test_items_invoice_route_needs_invoices_create_and_validates_every_item() -> None:
    """DL-103: one request makes one Miscellaneous DRAFT of up to 20 typed items."""
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id))
    path = f"/api/v1/properties/{property_id}/invoices/drafts"
    body = _items_body()
    items = cast(list[dict[str, object]], body["items"])
    denied = api(flow, actor(property_id, "invoices.issue")).post(
        path, headers=mutation_headers(), json=body
    )
    assert denied.status_code == 403 and flow.commands == []
    client = api(flow, actor(property_id, "invoices.create"))
    item = items[0]
    bad_bodies: list[dict[str, object]] = [
        {**body, "items": []},
        {**body, "items": [{**item, "charge_id": str(uuid4())} for _ in range(21)]},
        {**body, "items": [item, item]},
        {**body, "items": [{**item, "quantity": 1.5}]},
        {**body, "items": [{**item, "quantity": "2"}]},
        {**body, "items": [{**item, "quantity": 0}]},
        {**body, "items": [{**item, "quantity": 10_000}]},
        {**body, "items": [{**item, "unit_price_usd_cents": 0}]},
        {**body, "items": [{**item, "unit_price_usd_cents": 1_000_000_000}]},
        {**body, "items": [{**item, "unit_price_usd_cents": 12.5}]},
        {**body, "items": [{**item, "amount_usd_cents": 3000}]},
        {**body, "items": [{**item, "description": " Key copy"}]},
        {**body, "reason": ""},
    ]
    for bad in bad_bodies:
        assert client.post(path, headers=mutation_headers(), json=bad).status_code == 422
    assert flow.commands == []
    key = uuid4()
    created = client.post(path, headers=mutation_headers(key=key), json=body)
    assert created.status_code == 201
    assert created.headers["Location"] == f"/api/v1/invoices/{flow.value['id']}"
    assert created.headers["ETag"] == '"1"'
    command = cast(CreateItemsInvoiceDraftCommand, flow.commands[-1])
    assert command.items == (
        InvoiceItem(UUID(str(item["charge_id"])), "Key copy", 2, 1500),
        InvoiceItem(UUID(str(items[1]["charge_id"])), "Door lock", 1, 3999),
    )
    assert (command.reason, command.evidence_reference) == ("Keys and a lock", "Receipt 12")
    replay = client.post(path, headers=mutation_headers(key=key), json=body)
    assert replay.status_code == 201 and len(flow.commands) == 1
    changed = {**body, "reason": "Another reason"}
    reused = client.post(path, headers=mutation_headers(key=key), json=changed)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_edit_items_route_needs_the_version_and_the_reason_for_the_change() -> None:
    """DL-103: Edit items replaces the items of a DRAFT with one reason for the change."""
    property_id = uuid4()
    flow = InMemoryInvoiceFlow(property_id, invoice_resource(property_id, version=4))
    path = f"/api/v1/invoices/{flow.value['id']}/items"
    body = {**_items_body(), "change_reason": "Customer asked for one more key"}
    hidden = api(flow, actor(property_id, "invoices.issue")).put(
        path, headers=mutation_headers(version=4), json=body
    )
    assert hidden.status_code == 404 and flow.commands == []
    client = api(flow, actor(property_id, "invoices.create"))
    assert client.put(path, headers=mutation_headers(), json=body).status_code == 412
    no_reason = {key: value for key, value in body.items() if key != "change_reason"}
    assert client.put(path, headers=mutation_headers(version=4), json=no_reason).status_code == 422
    stale = client.put(path, headers=mutation_headers(version=3), json=body)
    assert stale.status_code == 412
    assert stale.json()["error"]["current_version"] == 4
    changed = client.put(path, headers=mutation_headers(version=4), json=body)
    assert changed.status_code == 200
    assert changed.headers["ETag"] == '"5"'
    command = cast(ReplaceInvoiceDraftItemsCommand, flow.commands[-1])
    assert command.change_reason == "Customer asked for one more key"
    assert command.expected_version == 4 and len(command.items) == 2
