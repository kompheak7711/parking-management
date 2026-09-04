"""Property-scoped staff billing visibility; commands retain their own authorization."""

from uuid import uuid4

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from test_invoice import InMemoryInvoiceFlow, actor, api, invoice_resource


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
