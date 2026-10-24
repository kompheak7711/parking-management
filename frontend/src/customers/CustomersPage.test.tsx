import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CustomerApi,
  CustomerDetail,
  CustomerListItem,
} from "../customerClient";
import type { CustomerLedgerApi } from "../customerLedgerClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import { CustomersPage } from "./CustomersPage";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/customers";
});

function item(
  id: string,
  legal_name: string,
  phone_number: string | null = null,
  active = true,
): CustomerListItem {
  return {
    customer_id: id,
    legal_name,
    phone_number,
    active,
    relationship_indicators: [],
  };
}

const customers = [
  item("customer-1", "Sok Dara", "012 345 678"),
  item("customer-2", "Chan Vanna", "099 111 222"),
  item("customer-3", "Lim Srey"),
  item("customer-4", "Keo Mony"),
  item("customer-5", "Pich Rina", null, false),
  item("customer-6", "Mok Thida"),
];

function signer(customer_id: string, customer_name: string, primary: boolean) {
  return {
    signer_id: `signer-${customer_id}`,
    customer_id,
    customer_name,
    is_primary_tenant: primary,
    signed_at: null,
    added_at: "2025-12-19T03:00:00Z",
  };
}

function lease(overrides: Partial<LeaseResource> = {}): LeaseResource {
  return {
    lease_id: "lease-1",
    property_id: "property-1",
    unit_id: "unit-U101",
    unit_number: "U101",
    primary_tenant_id: "customer-1",
    primary_tenant_name: "Sok Dara",
    status: "SIGNED",
    start_date: "2026-01-01",
    end_date: "2099-12-31",
    monthly_rent_usd_cents: 45000,
    predecessor_lease_id: null,
    signed_at: "2025-12-20T03:00:00Z",
    terminated_at: null,
    actual_termination_date: null,
    version: 1,
    created_at: "2025-12-19T03:00:00Z",
    pet_deposit_required: false,
    pet_description: null,
    security_deposit_id: null,
    planned_occupant_customer_ids: [],
    service_terms: [],
    signers: [
      signer("customer-1", "Sok Dara", true),
      signer("customer-2", "Chan Vanna", false),
    ],
    occupancies: [],
    timeline: [],
    timeline_next_cursor: null,
    can_edit: false,
    can_manage_signers: false,
    can_sign: false,
    can_terminate: false,
    can_move_in: false,
    can_renew: false,
    ...overrides,
  };
}

const leases = [
  // Mok Thida lived in U101 and moved out while the Lease still runs.
  lease({
    occupancies: [
      {
        occupancy_id: "occupancy-6",
        customer_id: "customer-6",
        customer_name: "Mok Thida",
        move_in_date: "2026-01-01",
        move_out_date: "2026-05-31",
        version: 2,
      },
    ],
  }),
  lease({
    lease_id: "lease-2",
    unit_id: "unit-U201",
    unit_number: "U201",
    primary_tenant_id: "customer-4",
    primary_tenant_name: "Keo Mony",
    status: "TERMINATED",
    start_date: "2025-01-01",
    end_date: "2025-12-31",
    actual_termination_date: "2025-09-15",
    signers: [signer("customer-4", "Keo Mony", true)],
  }),
];

const reservation = {
  reservation_id: "reservation-1",
  property_id: "property-1",
  unit_id: "unit-U102",
  unit_number: "U102",
  customer_id: "customer-3",
  customer_name: "Lim Srey",
  reservation_date: "2026-10-20",
  original_expiration_date: "2026-11-03",
  effective_expiration_date: "2026-11-03",
  agreed_monthly_rent_usd_cents: 38000,
  status: "ACTIVE",
} as unknown as ReservationResource;

function detail(overrides: Partial<CustomerDetail> = {}): CustomerDetail {
  return {
    customer_id: "customer-1",
    legal_name: "Sok Dara",
    phone_number: "012 345 678",
    email_address: "dara@example.com",
    contact_address: null,
    memo: null,
    id_document_number: "N0123456",
    date_of_birth: "1990-04-02",
    gender: "FEMALE",
    nationality: "Cambodian",
    version: 3,
    active: true,
    deactivated_at: null,
    deactivation_reason: null,
    relationships: {
      reservations: [],
      primary_tenant_leases: [],
      signer_leases: [],
      occupancies: [],
      invoices: [],
      payments: [],
      customer_credit: [],
      refunds: [],
    },
    audit_history: [
      {
        event_id: "event-1",
        occurred_at: "2026-01-02T03:00:00Z",
        actor_id: "actor-1",
        action: "customer.created",
        reason: "",
        previous_state: null,
        resulting_state: null,
        correlation_id: "c-1",
        outcome: "SUCCEEDED",
      },
    ],
    audit_history_next_cursor: null,
    can_manage: true,
    can_deactivate: true,
    can_view_audit: true,
    audit_history_available: true,
    ...overrides,
  };
}

function customerApi(overrides: Partial<CustomerApi> = {}): CustomerApi {
  return {
    list: vi.fn(
      (_: string, filters: { query?: string } = {}) =>
        Promise.resolve({
          items:
            filters.query === undefined
              ? customers
              : filters.query === "N0123456"
                ? [customers[0]]
                : [],
          next_cursor: null,
          can_manage: true,
        }) as ReturnType<CustomerApi["list"]>,
    ),
    get: vi.fn().mockResolvedValue(detail()),
    ...overrides,
  } as unknown as CustomerApi;
}

function leaseApi(
  list = vi.fn().mockResolvedValue({
    items: leases,
    next_cursor: null,
    can_create: true,
  }),
): LeaseApi {
  return { list } as unknown as LeaseApi;
}

function reservationApi(
  list = vi.fn().mockResolvedValue({
    items: [reservation],
    next_cursor: null,
    can_create: true,
  }),
): ReservationApi {
  return { list } as unknown as ReservationApi;
}

function ledgerApi(
  read = vi.fn().mockResolvedValue({
    section: "history",
    position: {
      invoice_usd_cents: "12000",
      charge_usd_cents: "500",
      total_owed_usd_cents: "12500",
      credit_usd_cents: "0",
      payment_usd_cents: "0",
      security_deposit_usd_cents: "45000",
      pet_deposit_usd_cents: "0",
    },
  }),
): CustomerLedgerApi {
  return { read } as unknown as CustomerLedgerApi;
}

function show(
  options: {
    customers?: CustomerApi;
    leases?: LeaseApi;
    reservations?: ReservationApi;
    ledger?: CustomerLedgerApi;
    onOpenLedger?: ((customerId: string) => void) | null;
  } = {},
) {
  return render(
    <CustomersPage
      active
      actorId="actor-1"
      capabilities={null}
      customerApi={options.customers ?? customerApi()}
      language="en"
      leaseApi={options.leases ?? leaseApi()}
      ledgerApi={options.ledger ?? ledgerApi()}
      onOpenLedger={options.onOpenLedger ?? null}
      propertyId="property-1"
      reservationApi={options.reservations ?? reservationApi()}
    />,
  );
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByRole("link", { name }).closest("tr");
  if (row === null) throw new Error(`no row for ${name}`);
  return row;
}

describe("Customers list", () => {
  it("TEST-FE-826 shows each Customer with the phone, the Unit and the relationship from the Leases and Reservations", async () => {
    show();

    expect(
      await screen.findByText(
        "6 people with a Lease, a Reservation or a history here",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Legal name", "Phone", "Unit", "Relationship"]);
    expect(rowOf("Sok Dara")).toHaveTextContent("012 345 678U101Tenant");
    expect(rowOf("Chan Vanna")).toHaveTextContent("U101Signer or occupant");
    expect(rowOf("Lim Srey")).toHaveTextContent("U102Reservation");
    expect(rowOf("Keo Mony")).toHaveTextContent("U201Former");
    expect(rowOf("Pich Rina")).toHaveTextContent("Deactivated");
    expect(rowOf("Pich Rina")).toHaveTextContent("No Lease yet");
    expect(rowOf("Mok Thida")).toHaveTextContent("U101Former");
    for (const label of [
      "Current tenants: 1.",
      "Signers and occupants: 1.",
      "Reservations: 1.",
      "Former: 2.",
    ])
      expect(
        screen.getByRole("button", { name: new RegExp(`^${label}`) }),
      ).toBeInTheDocument();
    expect(screen.getByText("6 Customers")).toBeInTheDocument();
  });

  it("TEST-FE-827 filters by count card and by name, phone or Unit, and Search asks the server for a whole ID number", async () => {
    const client = customerApi();
    show({ customers: client });
    await screen.findByText("6 Customers");

    fireEvent.click(screen.getByRole("button", { name: /^Former: 2\./ }));
    expect(screen.getByText("Showing: Former.")).toBeInTheDocument();
    expect(screen.getByText("2 Customers")).toBeInTheDocument();
    expect(rowOf("Keo Mony")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));

    const box = screen.getByRole("searchbox", {
      name: "Search by name, phone, Unit or ID number",
    });
    fireEvent.change(box, { target: { value: "345678" } });
    expect(screen.getByText("1 Customer")).toBeInTheDocument();
    expect(rowOf("Sok Dara")).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "u102" } });
    expect(rowOf("Lim Srey")).toBeInTheDocument();
    expect(screen.getByText("1 Customer")).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "N0123456" } });
    expect(screen.getByText("No Customers match.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("1 Customer")).toBeInTheDocument();
    expect(rowOf("Sok Dara")).toBeInTheDocument();
    expect(client.list).toHaveBeenCalledWith("property-1", {
      query: "N0123456",
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText("6 Customers")).toBeInTheDocument();
  });

  it("TEST-FE-828 shows dashes and a note when Leases cannot be read, and opens a Customer from the list", async () => {
    show({ leases: leaseApi(vi.fn().mockRejectedValue(new Error("403"))) });

    expect(
      await screen.findByText(
        "Your account cannot read Leases or Reservations, so Unit and Relationship show “—”.",
      ),
    ).toBeInTheDocument();
    expect(rowOf("Sok Dara")).toHaveTextContent("Sok Dara012 345 678——");
    expect(
      screen.queryByRole("button", { name: /^Current tenants/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "Sok Dara" }));
    expect(window.location.hash).toBe("#/customers/customer-1");
    expect(
      await screen.findByText(
        "Your account cannot read Leases or Reservations.",
      ),
    ).toBeInTheDocument();
  });
});

describe("Customer page", () => {
  it("TEST-FE-829 shows contact and identity, the Leases and Reservations, the money from the ledger and the history", async () => {
    window.location.hash = "#/customers/customer-1";
    const read = vi.fn().mockResolvedValue({
      section: "history",
      position: {
        invoice_usd_cents: "12000",
        charge_usd_cents: "500",
        total_owed_usd_cents: "12500",
        credit_usd_cents: "0",
        payment_usd_cents: "0",
        security_deposit_usd_cents: "45000",
        pet_deposit_usd_cents: "0",
      },
    });
    const open = vi.fn();
    show({ ledger: ledgerApi(read), onOpenLedger: open });

    expect(
      await screen.findByRole("heading", { name: "Sok Dara" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Primary Tenant · U101")).toBeInTheDocument();
    const contact = screen.getByRole("region", {
      name: "Contact and identity",
    });
    expect(contact).toHaveTextContent("012 345 678");
    expect(contact).toHaveTextContent("dara@example.com");
    expect(contact).toHaveTextContent("02/04/1990");
    expect(contact).toHaveTextContent("Female");
    expect(contact).toHaveTextContent("Cambodian");
    expect(contact).toHaveTextContent("N0123456");
    const rels = screen.getByRole("region", {
      name: "Leases and Reservations",
    });
    expect(rels).toHaveTextContent("U101 · Primary Tenant");
    expect(rels).toHaveTextContent("01/01/2026 – 31/12/2099");
    expect(rels).toHaveTextContent("Lease active");
    expect(within(rels).getByRole("link", { name: "U101" })).toHaveAttribute(
      "href",
      "#/units/unit-U101",
    );
    const money = screen.getByRole("region", { name: "Money" });
    await waitFor(() => {
      expect(money).toHaveTextContent("Unpaid$125.00");
    });
    expect(money).toHaveTextContent("Security Deposit$450.00");
    expect(money).not.toHaveTextContent("Pet Deposit");
    expect(read).toHaveBeenCalledWith(
      { section: "history", customerId: "customer-1", limit: 1 },
      expect.objectContaining({ actorId: "actor-1", propertyId: "property-1" }),
    );
    expect(screen.getByRole("region", { name: "History" })).toHaveTextContent(
      "Customer added.",
    );

    const [openLedger] = screen.getAllByRole("button", {
      name: "Open the Account Ledger",
    });
    if (openLedger === undefined) throw new Error("no ledger button");
    fireEvent.click(openLedger);
    expect(open).toHaveBeenCalledWith("customer-1");
  });

  it("TEST-FE-830 says when the money cannot be read or the Customer is not found", async () => {
    window.location.hash = "#/customers/customer-3";
    show({
      customers: customerApi({
        get: vi.fn().mockResolvedValue(
          detail({
            customer_id: "customer-3",
            legal_name: "Lim Srey",
            audit_history: [],
          }),
        ),
      }),
      ledger: ledgerApi(vi.fn().mockRejectedValue(new Error("403"))),
      onOpenLedger: vi.fn(),
    });

    expect(
      await screen.findByText(
        "Your account cannot read this Customer's money.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Reservation Customer · U102")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Leases and Reservations" }),
    ).toHaveTextContent("Reserved until 03/11/2026");
    expect(
      screen.queryByRole("button", { name: "Open the Account Ledger" }),
    ).not.toBeInTheDocument();
    cleanup();

    window.location.hash = "#/customers/customer-9";
    show({
      customers: customerApi({
        get: vi.fn().mockRejectedValue(new Error("404")),
      }),
    });
    expect(
      await screen.findByText(
        "This Customer was not found, or your account cannot open it.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(window.location.hash).toBe("#/customers");
  });
});
