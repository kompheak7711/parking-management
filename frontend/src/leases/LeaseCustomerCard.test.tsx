// UI v81 pilot (owner 08/11/2026 06:55): the Customer card of the Lease page. TEST-FE-1921.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi, CustomerDetail } from "../customerClient";
import type { CustomerLedgerApi, LedgerReply } from "../customerLedgerClient";
import type { LeaseResource } from "../leaseClient";
import { LeaseCustomerCard } from "./LeaseCustomerCard";

afterEach(() => {
  cleanup();
});

const lease = {
  lease_id: "lease-1",
  property_id: "property-1",
  unit_id: "unit-1",
  unit_number: "U206",
  primary_tenant_id: "customer-1",
  primary_tenant_name: "Keo Vannak",
} as LeaseResource;

const customer = {
  customer_id: "customer-1",
  legal_name: "Keo Vannak",
  phone_number: "+855 12 345 678",
  active: true,
} as CustomerDetail;

const ledgerReply = {
  section: "history",
  items: [],
  position: { credit_usd_cents: "2500", total_owed_usd_cents: "33000" },
} as unknown as LedgerReply;

describe("Lease page Customer card (UI v81 pilot)", () => {
  it("TEST-FE-1921 shows the Primary Tenant with the Lease status, the phone, Paid on time, the Customer Credit, the Unpaid Invoices and Open Customer; the Credit and Unpaid rows come from the Customer's ledger position", async () => {
    const get = vi.fn<CustomerApi["get"]>().mockResolvedValue(customer);
    const read = vi
      .fn<CustomerLedgerApi["read"]>()
      .mockResolvedValue(ledgerReply);
    const customerPaidOnTime = vi
      .fn()
      .mockResolvedValue({ on_time: 23, invoice_count: 23 });
    render(
      <LeaseCustomerCard
        actorId="actor-1"
        customerApi={{ get }}
        kind="current"
        language="en"
        lease={lease}
        ledgerApi={{ read }}
        mayCustomers
        mayInvoices
        propertyId="property-1"
        reports={{ customerPaidOnTime }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Customer" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Customer" })).toHaveAttribute(
      "href",
      "#/customers/customer-1",
    );
    expect(await screen.findByText("+855 12 345 678")).toBeInTheDocument();
    expect(screen.getByText("Keo Vannak")).toBeInTheDocument();
    expect(screen.getByText("Lease active")).toBeInTheDocument();
    expect(screen.getByText("Primary Tenant · U206")).toBeInTheDocument();
    expect(await screen.findByText("23 of 23 Invoices")).toBeInTheDocument();
    expect(await screen.findByText("$25.00")).toBeInTheDocument();
    expect(screen.getByText("$330.00")).toBeInTheDocument();
    // The owed box is marked while something is owed.
    expect(screen.getByText("Unpaid Invoices").closest(".ui-well")).toHaveClass(
      "owed",
    );
    // One ledger line is enough for the position; the read is scoped to the Property.
    expect(read).toHaveBeenCalledWith(
      { section: "history", customerId: "customer-1", limit: 1 },
      expect.objectContaining({ actorId: "actor-1", propertyId: "property-1" }),
    );
    expect(customerPaidOnTime).toHaveBeenCalledWith("property-1", "customer-1");
  });

  it("TEST-FE-1921 without the Customers right there is no Open Customer link, and a card without the ledger or reports says the rows could not be read, without crashing", () => {
    render(
      <LeaseCustomerCard
        customerApi={{} as CustomerApi}
        kind="draft"
        language="en"
        lease={lease}
        mayCustomers={false}
        mayInvoices={false}
        propertyId="property-1"
      />,
    );
    expect(screen.queryByRole("link", { name: "Open Customer" })).toBeNull();
    // The Lease's own name stands in while the Customer is not read.
    expect(screen.getByText("Keo Vannak")).toBeInTheDocument();
    expect(
      screen.getAllByText("Could not be read now.").length,
    ).toBeGreaterThan(1);
  });
});
