import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CustomerConflictError,
  CustomerIdNumberInUseError,
  CustomerRequestError,
  type CustomerApi,
  type CustomerDetail,
  type CustomerListItem,
  type VehicleResource,
} from "../customerClient";
import type { CustomerLedgerApi } from "../customerLedgerClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import { CustomersPage } from "./CustomersPage";
import type { CustomerCommandGate } from "./commands";

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
    planned_occupants: [],
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
    listVehicles: vi.fn().mockResolvedValue([]),
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

function commandGate(open = true): CustomerCommandGate {
  return {
    actorId: "actor-1",
    open,
    reserve: vi.fn().mockResolvedValue(true),
    release: vi.fn().mockResolvedValue(true),
    setBusy: vi.fn(),
  };
}

function show(
  options: {
    gate?: CustomerCommandGate;
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
      gate={options.gate ?? commandGate()}
      onDirty={vi.fn()}
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
  it("TEST-FE-826 shows each Customer with the phone, the Parking and the relationship from the Leases and Reservations", async () => {
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
    ).toEqual(["Legal name", "Phone", "Parking", "Relationship"]);
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

  it("TEST-FE-827 filters by count card and by name, phone or Parking, and Search asks the server for a whole ID number", async () => {
    const client = customerApi();
    show({ customers: client });
    await screen.findByText("6 Customers");

    fireEvent.click(screen.getByRole("button", { name: /^Former: 2\./ }));
    expect(screen.getByText("Showing: Former.")).toBeInTheDocument();
    expect(screen.getByText("2 Customers")).toBeInTheDocument();
    expect(rowOf("Keo Mony")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));

    const box = screen.getByRole("searchbox", {
      name: "Search by name, phone, Parking or ID number",
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
        "Your account cannot read Leases or Reservations, so Parking and Relationship show “—”.",
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

describe("Customer dialogs", () => {
  function field(name: string | RegExp): HTMLElement {
    return screen.getByLabelText(name);
  }

  it("TEST-FE-831 adds a Customer on the form page through the command gate and opens the new Customer", async () => {
    const created = detail({
      customer_id: "customer-new",
      legal_name: "Chea Sophal",
      id_document_number: "P7788",
      audit_history: [],
    });
    const create = vi.fn().mockResolvedValue(created);
    const client = customerApi({
      create,
      get: vi.fn().mockResolvedValue(created),
    });
    const gate = commandGate();
    show({ customers: client, gate });

    fireEvent.click(
      await screen.findByRole("button", { name: "Add Customer" }),
    );
    expect(window.location.hash).toBe("#/customers/new");
    const form = await screen.findByRole("form", { name: "Add Customer" });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );
    expect(within(form).getByText("Enter the legal name.")).toBeInTheDocument();
    expect(
      within(form).getByText("Enter the ID number or passport number."),
    ).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();

    fireEvent.change(field(/^Legal name/), {
      target: { value: "  Chea Sophal " },
    });
    fireEvent.change(field(/^ID number/), { target: { value: "P7788" } });
    fireEvent.change(field("Phone"), { target: { value: "012 888 999" } });
    fireEvent.change(field("Gender"), { target: { value: "MALE" } });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );

    expect(
      await screen.findByText("Chea Sophal was added."),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe("#/customers/customer-new");
    expect(create).toHaveBeenCalledTimes(1);
    const [propertyId, customerId, source, key] = create.mock.calls[0] as [
      string,
      string,
      Record<string, unknown>,
      string,
    ];
    expect(propertyId).toBe("property-1");
    expect(source).toMatchObject({
      legal_name: "Chea Sophal",
      id_document_number: "P7788",
      phone_number: "012 888 999",
      gender: "MALE",
      email_address: null,
    });
    const reserved = vi.mocked(gate.reserve).mock.calls[0]?.[0];
    expect(reserved).toMatchObject({
      kind: "create",
      customerId,
      commandNonce: key,
      propertyId: "property-1",
    });
    expect(gate.release).toHaveBeenCalledWith(reserved);
  });

  it("TEST-FE-1117 an impossible day typed as yyyy-mm-dd is refused before anything is sent (V1-061 Fix 4)", async () => {
    const create = vi.fn();
    show({ customers: customerApi({ create }), gate: commandGate() });
    fireEvent.click(
      await screen.findByRole("button", { name: "Add Customer" }),
    );
    const form = await screen.findByRole("form", { name: "Add Customer" });
    fireEvent.change(field(/^Legal name/), {
      target: { value: "Chea Sophal" },
    });
    fireEvent.change(field(/^ID number/), { target: { value: "P7788" } });
    fireEvent.change(field(/^Date of birth/), {
      target: { value: "1990-02-30" },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );
    expect(within(form).getByText("Pick a date.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("TEST-FE-832 warns about a Customer with the same name or phone and saves only after the tick; a used ID number is an error", async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(
        new CustomerConflictError([
          item("customer-1", "Sok Dara", "012 345 678"),
        ]),
      )
      .mockResolvedValueOnce(
        detail({ customer_id: "customer-new", legal_name: "Sok Dara" }),
      );
    const gate = commandGate();
    window.location.hash = "#/customers/new";
    show({ customers: customerApi({ create }), gate });

    const form = await screen.findByRole("form", { name: "Add Customer" });
    fireEvent.change(field(/^Legal name/), { target: { value: "Sok Dara" } });
    fireEvent.change(field(/^ID number/), { target: { value: "P1" } });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );
    expect(
      await within(form).findByText(/A Customer with the same name or phone/),
    ).toBeInTheDocument();
    expect(
      within(form).getByRole("link", { name: "Sok Dara" }),
    ).toHaveAttribute("href", "#/customers/customer-1");
    expect(gate.release).toHaveBeenCalledTimes(1);

    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );
    expect(
      within(form).getByText(/Tick “This is a different person”/),
    ).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(1);

    fireEvent.click(
      within(form).getByRole("checkbox", {
        name: "This is a different person; save anyway",
      }),
    );
    fireEvent.click(
      within(form).getByRole("button", { name: "Save Customer" }),
    );
    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(2);
    });
    expect(create.mock.calls[1]?.[2]).toMatchObject({
      confirmed_distinct: true,
    });
    cleanup();

    window.location.hash = "#/customers/new";
    show({
      customers: customerApi({
        create: vi
          .fn()
          .mockRejectedValue(
            new CustomerIdNumberInUseError([item("customer-4", "Keo Mony")]),
          ),
      }),
    });
    const second = await screen.findByRole("form", { name: "Add Customer" });
    fireEvent.change(field(/^Legal name/), { target: { value: "Keo M" } });
    fireEvent.change(field(/^ID number/), { target: { value: "N9" } });
    fireEvent.click(
      within(second).getByRole("button", { name: "Save Customer" }),
    );
    expect(
      await within(second).findByText(
        "Another Customer already has this ID number or passport number.",
      ),
    ).toBeInTheDocument();
    expect(
      within(second).getByRole("link", { name: "Keo Mony" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-833 Edit contact sends only the changed fields with the version, and reloads when someone else changed the Customer first", async () => {
    window.location.hash = "#/customers/customer-1";
    const update = vi
      .fn()
      .mockResolvedValueOnce(
        detail({ phone_number: "011 222 333", version: 4 }),
      )
      .mockRejectedValueOnce(new CustomerConflictError());
    const get = vi.fn().mockResolvedValue(detail());
    show({ customers: customerApi({ update, get }) });

    fireEvent.click(
      await screen.findByRole("button", { name: "Edit contact" }),
    );
    let dialog = screen.getByRole("dialog", {
      name: "Edit contact · Sok Dara",
    });
    expect(within(dialog).getByLabelText("Phone")).toHaveValue("012 345 678");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Nothing was changed."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Phone"), {
      target: { value: " 011 222 333 " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("The contact details of Sok Dara were saved."),
    ).toBeInTheDocument();
    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({ customer_id: "customer-1", version: 3 }),
      { phone_number: "011 222 333" },
      expect.any(String),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit contact" }));
    dialog = screen.getByRole("dialog", { name: "Edit contact · Sok Dara" });
    fireEvent.change(within(dialog).getByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(/Someone else changed this Customer first/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(get.mock.calls.length).toBeGreaterThanOrEqual(3);
    });
  });

  it("TEST-FE-834 keeps the gate when the result is unknown, and Try again sends the very same save", async () => {
    window.location.hash = "#/customers/customer-1";
    const update = vi
      .fn()
      .mockRejectedValueOnce(
        new CustomerRequestError("unknown", [], null, true),
      )
      .mockResolvedValueOnce(detail({ memo: "Late riser", version: 4 }));
    const gate = commandGate();
    show({ customers: customerApi({ update }), gate });

    fireEvent.click(
      await screen.findByRole("button", { name: "Edit contact" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Edit contact · Sok Dara",
    });
    fireEvent.change(within(dialog).getByLabelText("Memo"), {
      target: { value: "Late riser" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        /We could not tell whether this was saved/,
      ),
    ).toBeInTheDocument();
    expect(gate.release).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText("The contact details of Sok Dara were saved."),
    ).toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[2]).toBe(update.mock.calls[0]?.[2]);
    expect(gate.reserve).toHaveBeenCalledTimes(1);
    expect(gate.release).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-835 deactivates with a required reason, and sends nothing while another save waits to be checked", async () => {
    window.location.hash = "#/customers/customer-1";
    const deactivate = vi
      .fn()
      .mockResolvedValue(detail({ active: false, version: 4 }));
    show({ customers: customerApi({ deactivate }) });

    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    const dialog = screen.getByRole("dialog", {
      name: "Deactivate · Sok Dara",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(within(dialog).getByText("Enter the reason.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Moved abroad" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(
      await screen.findByText("Sok Dara was deactivated."),
    ).toBeInTheDocument();
    expect(deactivate).toHaveBeenCalledWith(
      expect.objectContaining({ customer_id: "customer-1" }),
      "Moved abroad",
      expect.any(String),
    );
    cleanup();

    window.location.hash = "#/customers/customer-1";
    const update = vi.fn();
    show({ customers: customerApi({ update }), gate: commandGate(false) });
    expect(
      await screen.findByText(/A Customer save is waiting to be checked/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit contact" }));
    const blocked = screen.getByRole("dialog", {
      name: "Edit contact · Sok Dara",
    });
    fireEvent.change(within(blocked).getByLabelText("Memo"), {
      target: { value: "x" },
    });
    fireEvent.click(within(blocked).getByRole("button", { name: "Save" }));
    expect(
      await within(blocked).findByText(/^Nothing was sent/),
    ).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("TEST-FE-836 hides Add Customer, Edit contact and Deactivate without the server's permission", async () => {
    show({
      customers: customerApi({
        list: vi.fn().mockResolvedValue({
          items: customers,
          next_cursor: null,
          can_manage: false,
        }),
        get: vi
          .fn()
          .mockResolvedValue(
            detail({ can_manage: false, can_deactivate: false }),
          ),
      }),
    });
    await screen.findByText("6 Customers");
    expect(
      screen.queryByRole("button", { name: "Add Customer" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Sok Dara" }));
    await screen.findByRole("heading", { name: "Sok Dara" });
    expect(
      screen.queryByRole("button", { name: "Edit contact" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Deactivate" }),
    ).not.toBeInTheDocument();
  });
});

// Parking Step 4 (owner 2026-10-30): vehicles under a Customer.
describe("Vehicles (Parking Step 4)", () => {
  function vehicle(
    id: string,
    plate: string,
    type: VehicleResource["vehicle_type"] = "CAR",
    owner = "customer-1",
    ownerName = "Sok Dara",
  ): VehicleResource {
    return {
      vehicle_id: id,
      customer_id: owner,
      customer_name: ownerName,
      vehicle_type: type,
      plate_text: plate,
      version: 1,
    };
  }

  it("TEST-FE-1127 the Vehicles card lists the Customer's vehicles and Add vehicle saves the type and the plate as typed", async () => {
    window.location.hash = "#/customers/customer-1";
    const listVehicles = vi
      .fn<CustomerApi["listVehicles"]>()
      .mockResolvedValueOnce([vehicle("vehicle-1", "1AB-1234", "MOTORBIKE")])
      .mockResolvedValue([
        vehicle("vehicle-1", "1AB-1234", "MOTORBIKE"),
        vehicle("vehicle-2", "ភ្នំពេញ 2CD 5678", "TUK_TUK"),
      ]);
    const createVehicle = vi
      .fn<CustomerApi["createVehicle"]>()
      .mockResolvedValue(vehicle("vehicle-2", "ភ្នំពេញ 2CD 5678", "TUK_TUK"));
    const findVehiclesByPlate = vi
      .fn<CustomerApi["findVehiclesByPlate"]>()
      .mockResolvedValue([]);
    show({
      customers: customerApi({
        listVehicles,
        createVehicle,
        findVehiclesByPlate,
      }),
    });
    const card = await screen.findByRole("region", { name: "Vehicles" });
    expect(await within(card).findByText("1AB-1234")).toBeInTheDocument();
    expect(within(card).getByText("Motorbike")).toBeInTheDocument();
    expect(listVehicles).toHaveBeenCalledWith("customer-1");

    fireEvent.click(within(card).getByRole("button", { name: "Add vehicle" }));
    const dialog = screen.getByRole("dialog", {
      name: "Add vehicle · Sok Dara",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Type the plate.")).toBeInTheDocument();
    expect(createVehicle).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Type"), {
      target: { value: "TUK_TUK" },
    });
    fireEvent.change(within(dialog).getByLabelText("Plate"), {
      target: { value: " ភ្នំពេញ 2CD 5678 " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Vehicle ភ្នំពេញ 2CD 5678 was added."),
    ).toBeInTheDocument();
    expect(findVehiclesByPlate).toHaveBeenCalledWith(
      "property-1",
      "ភ្នំពេញ 2CD 5678",
    );
    expect(createVehicle).toHaveBeenCalledTimes(1);
    expect(createVehicle.mock.calls[0]?.[0]).toBe("customer-1");
    expect(createVehicle.mock.calls[0]?.[1]).toMatchObject({
      vehicle_type: "TUK_TUK",
      plate_text: "ភ្នំពេញ 2CD 5678",
    });
    expect(typeof createVehicle.mock.calls[0]?.[1].vehicle_id).toBe("string");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      await within(card).findByText("ភ្នំពេញ 2CD 5678"),
    ).toBeInTheDocument();
    expect(within(card).getByText("Tuk-tuk")).toBeInTheDocument();
  });

  it("TEST-FE-1128 a plate another vehicle already has warns with the owner's name and saves only on Save anyway; nothing is merged", async () => {
    window.location.hash = "#/customers/customer-1";
    const createVehicle = vi
      .fn<CustomerApi["createVehicle"]>()
      .mockResolvedValue(vehicle("vehicle-9", "1ab 1234"));
    const findVehiclesByPlate = vi
      .fn<CustomerApi["findVehiclesByPlate"]>()
      .mockResolvedValue([
        vehicle("vehicle-7", "1AB-1234", "CAR", "customer-2", "Chan Vanna"),
      ]);
    show({
      customers: customerApi({
        listVehicles: vi
          .fn<CustomerApi["listVehicles"]>()
          .mockResolvedValue([]),
        createVehicle,
        findVehiclesByPlate,
      }),
    });
    const card = await screen.findByRole("region", { name: "Vehicles" });
    expect(within(card).getByText("No vehicle yet.")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Add vehicle" }));
    const dialog = screen.getByRole("dialog", {
      name: "Add vehicle · Sok Dara",
    });
    fireEvent.change(within(dialog).getByLabelText("Plate"), {
      target: { value: "1ab 1234" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "Another vehicle has this plate: Chan Vanna (1AB-1234).",
      ),
    ).toBeInTheDocument();
    expect(createVehicle).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save anyway" }),
    );
    expect(
      await screen.findByText("Vehicle 1ab 1234 was added."),
    ).toBeInTheDocument();
    expect(createVehicle).toHaveBeenCalledTimes(1);
    expect(createVehicle.mock.calls[0]?.[1].plate_text).toBe("1ab 1234");
  });

  it("TEST-FE-1137 a failed plate lookup does not stop the save, and the plate box stops at 32 characters", async () => {
    window.location.hash = "#/customers/customer-1";
    const createVehicle = vi
      .fn<CustomerApi["createVehicle"]>()
      .mockResolvedValue(vehicle("vehicle-3", "3EF-9012"));
    show({
      customers: customerApi({
        listVehicles: vi
          .fn<CustomerApi["listVehicles"]>()
          .mockResolvedValue([]),
        createVehicle,
        findVehiclesByPlate: vi
          .fn<CustomerApi["findVehiclesByPlate"]>()
          .mockRejectedValue(new Error("down")),
      }),
    });
    const card = await screen.findByRole("region", { name: "Vehicles" });
    fireEvent.click(within(card).getByRole("button", { name: "Add vehicle" }));
    const dialog = screen.getByRole("dialog", {
      name: "Add vehicle · Sok Dara",
    });
    expect(within(dialog).getByLabelText("Plate")).toHaveAttribute(
      "maxlength",
      "32",
    );
    fireEvent.change(within(dialog).getByLabelText("Plate"), {
      target: { value: "3EF-9012" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Vehicle 3EF-9012 was added."),
    ).toBeInTheDocument();
    expect(createVehicle).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-1129 Edit corrects the type and the plate with the version; a reader and a deactivated Customer get no Add vehicle", async () => {
    window.location.hash = "#/customers/customer-1";
    const updateVehicle = vi
      .fn<CustomerApi["updateVehicle"]>()
      .mockResolvedValue({
        ...vehicle("vehicle-1", "1AB-9999", "CAR"),
        version: 2,
      });
    show({
      customers: customerApi({
        listVehicles: vi
          .fn<CustomerApi["listVehicles"]>()
          .mockResolvedValue([vehicle("vehicle-1", "1AB-1234", "MOTORBIKE")]),
        updateVehicle,
        findVehiclesByPlate: vi
          .fn<CustomerApi["findVehiclesByPlate"]>()
          .mockResolvedValue([vehicle("vehicle-1", "1AB-1234", "MOTORBIKE")]),
      }),
    });
    const card = await screen.findByRole("region", { name: "Vehicles" });
    fireEvent.click(await within(card).findByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", {
      name: "Edit vehicle · 1AB-1234",
    });
    expect(within(dialog).getByLabelText("Type")).toHaveValue("MOTORBIKE");
    fireEvent.change(within(dialog).getByLabelText("Type"), {
      target: { value: "CAR" },
    });
    fireEvent.change(within(dialog).getByLabelText("Plate"), {
      target: { value: "1AB-9999" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Vehicle 1AB-9999 was saved."),
    ).toBeInTheDocument();
    // The vehicle's own plate is not a duplicate of itself.
    expect(updateVehicle).toHaveBeenCalledWith(
      expect.objectContaining({ vehicle_id: "vehicle-1", version: 1 }),
      { vehicle_type: "CAR", plate_text: "1AB-9999" },
    );

    cleanup();
    window.location.hash = "#/customers/customer-1";
    show({
      customers: customerApi({
        get: vi.fn().mockResolvedValue(detail({ can_manage: false })),
        listVehicles: vi
          .fn<CustomerApi["listVehicles"]>()
          .mockResolvedValue([]),
      }),
    });
    const reading = await screen.findByRole("region", { name: "Vehicles" });
    expect(
      within(reading).queryByRole("button", { name: "Add vehicle" }),
    ).toBeNull();
  });
});
