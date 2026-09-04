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
