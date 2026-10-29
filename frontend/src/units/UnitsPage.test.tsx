import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import { detailFromHash, hashForPage, pageFromHash } from "../shell/navigation";
import {
  UnitApi,
  UnitConflictError,
  UnitInventory,
  UnitResource,
  UnitSetupItem,
  UnitSetupListKind,
  UnitSetupLists,
} from "../unitClient";
import { UnitsPage } from "./UnitsPage";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/units";
});

function setupItem(
  list_kind: UnitSetupListKind,
  code: string,
  name_en: string,
  removed = false,
): UnitSetupItem {
  return {
    item_id: `${list_kind}-${code}`,
    list_kind,
    code,
    name_en,
    name_km: null,
    sort_order: 10,
    removed,
    in_use: false,
    version: 1,
  };
}

const lists: UnitSetupLists = {
  lists: {
    FLOOR: [
      setupItem("FLOOR", "F001", "1"),
      setupItem("FLOOR", "F002", "2"),
      setupItem("FLOOR", "F009", "Old roof", true),
    ],
    UNIT_TYPE: [
      setupItem("UNIT_TYPE", "STUDIO", "Studio"),
      setupItem("UNIT_TYPE", "ONE_BEDROOM", "1 bedroom"),
      setupItem("UNIT_TYPE", "PENTHOUSE", "Penthouse", true),
    ],
    VIEW: [setupItem("VIEW", "RIVER", "River view")],
    KITCHEN: [],
    ROOM_FEATURE: [setupItem("ROOM_FEATURE", "BALCONY", "Balcony")],
  },
  can_manage: false,
};

function unit(
  number: string,
  overrides: Partial<UnitResource> = {},
): UnitResource {
  return {
    unit_id: `unit-${number}`,
    property_id: "property-1",
    unit_number: number,
    floor: "1",
    floor_item_id: "FLOOR-F001",
    unit_type: "STUDIO",
    status: "VACANT",
    version: 2,
    size_square_metres: "36.00",
    bedrooms: 1,
    bathrooms: 1,
    view_item_id: "VIEW-RIVER",
    kitchen_item_id: null,
    notes: null,
    room_feature_ids: ["ROOM_FEATURE-BALCONY"],
    current_reservation: null,
    current_lease: null,
    current_occupancy: null,
    active_meter_summary: null,
    operational_alerts: [],
    can_manage: true,
    ...overrides,
  };
}

const u101 = unit("U101", { status: "OCCUPIED" });
const u102 = unit("U102", { status: "RESERVED", unit_type: "ONE_BEDROOM" });
const u201 = unit("U201", { floor: "2", floor_item_id: "FLOOR-F002" });
const u202 = unit("U202", {
  floor: "2",
  floor_item_id: "FLOOR-F002",
  status: "UNDER_MAINTENANCE",
});
const units = [u101, u102, u201, u202];

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
      {
        signer_id: "signer-1",
        customer_id: "customer-1",
        customer_name: "Sok Dara",
        is_primary_tenant: true,
        signed_at: null,
        added_at: "2025-12-19T03:00:00Z",
      },
      {
        signer_id: "signer-2",
        customer_id: "customer-2",
        customer_name: "Chan Vanna",
        is_primary_tenant: false,
        signed_at: null,
        added_at: "2025-12-19T03:00:00Z",
      },
    ],
    occupancies: [
      {
        occupancy_id: "occupancy-1",
        customer_id: "customer-1",
        customer_name: "Sok Dara",
        move_in_date: "2026-01-01",
        move_out_date: null,
        version: 1,
      },
    ],
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
  version: 1,
  deposit_id: "deposit-1",
  deposit_required_usd_cents: 10000,
  deposit_received_usd_cents: 10000,
  deposit_outcome_state: "HELD",
  cancellation_reason_code: null,
  cancellation_responsibility: null,
  resulting_lease_id: null,
  extension_notice: null,
  can_extend: true,
  can_cancel: true,
  receipts: [],
  lifecycle_events: [],
} as unknown as ReservationResource;

const inventory: UnitInventory = {
  unit_id: "unit-U201",
  record_number: 0,
  recorded_at: null,
  recorded_by: null,
  lines: [],
  counts: { FURNITURE: 0, APPLIANCES: 0, KITCHEN: 0, BATHROOM: 0 },
  can_manage: true,
};

function unitApi(overrides: Partial<UnitApi> = {}): UnitApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: units,
      next_cursor: null,
      can_manage: true,
    }),
    get: vi.fn((unitId: string) =>
      Promise.resolve(units.find((entry) => entry.unit_id === unitId) ?? u101),
    ),
    create: vi.fn().mockResolvedValue(unit("U107")),
    update: vi.fn().mockResolvedValue(unit("U201", { version: 3 })),
    timeline: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    setupLists: vi.fn().mockResolvedValue(lists),
    createSetupItem: vi.fn(),
    updateSetupItem: vi.fn(),
    removeSetupItem: vi.fn(),
    inventory: vi.fn().mockResolvedValue(inventory),
    saveInventory: vi.fn(),
    inventoryItems: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}

function leaseApi(list = vi.fn()): LeaseApi {
  list.mockImplementation((_: string, filters: { unit_id?: string } = {}) =>
    Promise.resolve({
      items:
        filters.unit_id === undefined
          ? [lease()]
          : [lease()].filter((entry) => entry.unit_id === filters.unit_id),
      next_cursor: null,
      can_create: true,
    }),
  );
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

function show(
  client: UnitApi,
  options: {
    leases?: LeaseApi;
    reservations?: ReservationApi;
    capabilities?: ReadonlySet<string> | null;
  } = {},
) {
  return render(
    <UnitsPage
      active
      capabilities={options.capabilities ?? null}
      language="en"
      leaseApi={options.leases ?? leaseApi()}
      propertyId="property-1"
      reservationApi={options.reservations ?? reservationApi()}
      unitApi={client}
    />,
  );
}

function rowOf(number: string): HTMLElement {
  const row = screen.getByRole("link", { name: number }).closest("tr");
  if (row === null) throw new Error(`no row for ${number}`);
  return row;
}

describe("Units list", () => {
  it("TEST-FE-027 shows the Units table with status chips, Until from the Lease or Reservation, and New Unit for a manager", async () => {
    show(unitApi());

    expect(
      await screen.findByText("4 Units at CHETANA Parking"),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Unit", "Floor", "Unit Type", "Status", "Until"]);
    // The owner removed Customer and Monthly Rent (28/10/2026).
    const occupied = rowOf("U101");
    expect(occupied).toHaveTextContent("Floor 1");
    expect(occupied).toHaveTextContent("Occupied");
    expect(occupied).toHaveTextContent("31/12/2099");
    expect(occupied).not.toHaveTextContent("Sok Dara");
    expect(occupied).not.toHaveTextContent("$450.00");
    const reserved = rowOf("U102");
    expect(reserved).toHaveTextContent("1 bedroom");
    expect(reserved).toHaveTextContent("03/11/2026Reserved until");
    expect(reserved).not.toHaveTextContent("Lim Srey");
    expect(rowOf("U202")).toHaveTextContent("Under maintenance");
    expect(rowOf("U201")).toHaveTextContent("Vacant");
    expect(screen.getByText("4 Units")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New Unit" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1024 Until shows the End Date of a signed Lease that starts later, and of the running Lease when a renewal is signed", async () => {
    const list = vi.fn().mockResolvedValue({
      items: [
        // U101: the running Lease and its signed renewal.
        lease({ start_date: "2025-01-01", end_date: "2026-12-31" }),
        lease({
          lease_id: "lease-renewal",
          start_date: "2027-01-01",
          end_date: "2027-12-31",
        }),
        // U201: signed, the Unit is Occupied, the Lease starts later.
        lease({
          lease_id: "lease-later",
          unit_id: "unit-U201",
          unit_number: "U201",
          start_date: "2099-11-01",
          end_date: "2100-10-31",
        }),
      ],
      next_cursor: null,
      can_create: true,
    });
    show(unitApi(), { leases: { list } as unknown as LeaseApi });
    await screen.findByText("4 Units at CHETANA Parking");

    expect(rowOf("U101")).toHaveTextContent("31/12/2026");
    expect(rowOf("U201")).toHaveTextContent("31/10/2100");
    // Every signed Lease is read, not only the ones running today.
    expect(list).toHaveBeenCalledWith("property-1", { status: "SIGNED" });
  });

  it("TEST-FE-028 hides New Unit, Change status and Update Unit without the server's permission", async () => {
    const client = unitApi({
      list: vi.fn().mockResolvedValue({
        items: units.map((entry) => ({ ...entry, can_manage: false })),
        next_cursor: null,
        can_manage: false,
      }),
      get: vi.fn().mockResolvedValue({ ...u201, can_manage: false }),
    });
    show(client);
    await screen.findByText("4 Units at CHETANA Parking");
    expect(
      screen.queryByRole("button", { name: "New Unit" }),
    ).not.toBeInTheDocument();

    window.location.hash = "#/units/unit-U201";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "U201" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change status" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Update Unit" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-823 filters by floor, Unit Type and the four count cards", async () => {
    show(unitApi());
    await screen.findByText("4 Units at CHETANA Parking");
    const card = (name: RegExp) => screen.getByRole("button", { name });

    expect(card(/^Occupied: 1/)).toBeInTheDocument();
    expect(card(/^Not available: 1/)).toBeInTheDocument();
    fireEvent.click(card(/^Not available/));
    expect(card(/^Not available/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Showing: Not available\./)).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getAllByRole("row")).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: "Floor 2" }));
    expect(screen.getByText("2 Units")).toBeInTheDocument();
    expect(card(/^Occupied: 0/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All floors" }));
    fireEvent.change(screen.getByLabelText("Unit Type"), {
      target: { value: "ONE_BEDROOM" },
    });
    expect(screen.getByText("1 Unit")).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Penthouse" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-825 opens a Unit by its address and shows “—” when Leases cannot be read", async () => {
    expect(pageFromHash("#/units/unit-U101")).toBe("units");
    expect(detailFromHash("#/units/unit-U101")).toBe("unit-U101");
    expect(detailFromHash("#/units")).toBeNull();
    expect(detailFromHash("#/nothing/x")).toBeNull();
    expect(detailFromHash("#/units/%E0")).toBeNull();
    expect(hashForPage("units", "a b")).toBe("#/units/a%20b");

    show(unitApi(), {
      leases: { list: vi.fn().mockRejectedValue(new Error("403")) } as never,
    });
    expect(
      await screen.findByText(/cannot read Leases or Reservations/),
    ).toBeInTheDocument();
    expect(rowOf("U101")).toHaveTextContent("—");
    fireEvent.click(screen.getByRole("link", { name: "U201" }));
    expect(window.location.hash).toBe("#/units/unit-U201");
    expect(
      await screen.findByRole("heading", { name: "U201" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-030 names a list that could not be read and a change someone else made first", async () => {
    const list = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({ items: units, next_cursor: null, can_manage: true });
    const update = vi.fn().mockRejectedValue(new UnitConflictError());
    const client = unitApi({ list, update });
    show(client);
    expect(
      await screen.findByText(
        "The Units could not be read. Retry when the service is available.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("4 Units at CHETANA Parking");

    window.location.hash = "#/units/unit-U201";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    fireEvent.click(await screen.findByRole("button", { name: "Update Unit" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }),
    );
    expect(
      await screen.findByText(/Someone else changed this Unit first\./),
    ).toBeInTheDocument();
    // The dialog closes, so the next save starts from the latest details.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(client.get).toHaveBeenCalledTimes(2);
    });
  });
});

describe("Unit page", () => {
  it("TEST-FE-029 keeps the Unit details, Lease, Meters, Invoices and History apart and lists the History", async () => {
    window.location.hash = "#/units/unit-U101";
    const client = unitApi({
      timeline: vi.fn().mockResolvedValue({
        items: [
          {
            event_id: "event-2",
            occurred_at: "2026-10-24T05:30:00Z",
            actor_id: "actor-1",
            action: "unit.status_changed",
            entity_type: "unit",
            reason: "Aircon repaired",
            previous_state: { status: "UNDER_MAINTENANCE" },
            resulting_state: { status: "VACANT" },
            correlation_id: "event-2",
            outcome: "SUCCEEDED",
          },
          {
            event_id: "event-1",
            occurred_at: "2025-08-24T00:00:00Z",
            actor_id: "actor-1",
            action: "unit.created",
            entity_type: "unit",
            reason: "Created",
            previous_state: null,
            resulting_state: { status: "VACANT" },
            correlation_id: "event-1",
            outcome: "SUCCEEDED",
          },
        ],
        next_cursor: null,
      }),
    });
    show(client);

    expect(
      await screen.findByRole("heading", { name: "U101" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Floor 1 · Studio · 36 m² · CHETANA Parking"),
    ).toBeInTheDocument();
    for (const name of [
      "Unit details",
      "Current Lease",
      "Lease history",
      "Meters",
      "Invoices for this Unit",
      "History",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    const details = screen
      .getByRole("heading", { name: "Unit details" })
      .closest("section");
    if (details === null) throw new Error("no details card");
    expect(details).toHaveTextContent("BalconyYes");
    expect(details).toHaveTextContent("ViewRiver view");
    expect(details).toHaveTextContent("KitchenNot recorded");
    const leaseCard = screen
      .getByRole("heading", { name: "Current Lease" })
      .closest("section");
    if (leaseCard === null) throw new Error("no Lease card");
    expect(leaseCard).toHaveTextContent("Primary TenantSok Dara");
    expect(leaseCard).toHaveTextContent("SignersSok Dara, Chan Vanna");
    expect(leaseCard).toHaveTextContent("Period01/01/2026 – 31/12/2099");
    const history = screen
      .getByRole("heading", { name: "History" })
      .closest("section");
    if (history === null) throw new Error("no History card");
    const lines = within(history).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent(
      "Status changed to Vacant: Aircon repaired24/10/2026 12:30",
    );
    expect(history).toHaveTextContent("Lease signed by Sok Dara.");
    expect(history).toHaveTextContent("Sok Dara moved in.");
    expect(history).toHaveTextContent("Unit created.");
    for (const link of screen.getAllByRole("link", { name: "Open Lease" })) {
      expect(link).toHaveAttribute("href", "#/leases/lease-1");
    }
  });

  it("TEST-FE-1074 each button opens its own place: New Lease opens the form with the Unit chosen or the draft from its Reservation, and Open Lease, Open draft Lease and Open Reservation open that record", async () => {
    const all = [
      lease(),
      lease({
        lease_id: "lease-draft",
        unit_id: "unit-U202",
        unit_number: "U202",
        status: "DRAFTED",
        signed_at: null,
      }),
    ];
    const leases = {
      list: vi.fn((_: string, filters: { unit_id?: string } = {}) =>
        Promise.resolve({
          items:
            filters.unit_id === undefined
              ? all
              : all.filter((entry) => entry.unit_id === filters.unit_id),
          next_cursor: null,
          can_create: true,
        }),
      ),
    } as unknown as LeaseApi;
    const client = unitApi();
    const hrefs = (name: string) =>
      screen
        .getAllByRole("link", { name })
        .map((link) => link.getAttribute("href"));
    const open = async (number: string) => {
      window.location.hash = `#/units/unit-${number}`;
      const view = show(client, { leases });
      expect(
        await screen.findByRole("heading", { name: number }),
      ).toBeInTheDocument();
      return view;
    };

    let view = await open("U201");
    expect(hrefs("New Lease")).toEqual(["#/leases/unit%3Aunit-U201"]);
    expect(hrefs("Make Reservation")).toEqual([
      "#/reservations/new%3Aunit-U201",
    ]);
    view.unmount();

    view = await open("U102");
    expect(hrefs("New Lease from Reservation")).toEqual([
      "#/leases/new%3Areservation-1",
    ]);
    // The head and the Reservation card.
    expect(hrefs("Open Reservation")).toEqual([
      "#/reservations/reservation-1",
      "#/reservations/reservation-1",
    ]);
    view.unmount();

    view = await open("U202");
    expect(hrefs("Open draft Lease")).toEqual(["#/leases/lease-draft"]);
    expect(hrefs("New Lease")).toEqual(["#/leases/unit%3Aunit-U202"]);
    view.unmount();

    await open("U101");
    // The head and the Current Lease card.
    expect(hrefs("Open Lease")).toEqual([
      "#/leases/lease-1",
      "#/leases/lease-1",
    ]);
    expect(screen.queryByRole("link", { name: "New Lease" })).toBeNull();
  });

  it("TEST-FE-824 changes the status only with a reason and not while a Lease holds the Unit", async () => {
    window.location.hash = "#/units/unit-U101";
    const update = vi
      .fn()
      .mockResolvedValue(
        unit("U202", { status: "VACANT", floor: "2", version: 3 }),
      );
    const client = unitApi({ update });
    const { unmount } = show(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Change status" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "This Unit has a signed Lease. Its status changes only through Move-out.",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();

    window.location.hash = "#/units/unit-U202";
    show(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Change status" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog)
        .getAllByRole("radio")
        .map((radio) => radio.closest("label")?.textContent),
    ).toEqual(["Vacant", "Cleaning", "Under maintenance", "Out of service"]);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Vacant" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Give the reason for the change."),
    ).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: " Aircon repaired " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("U202 is now Vacant.")).toBeInTheDocument();
    expect(update).toHaveBeenCalledWith(u202, {
      status: "VACANT",
      reason: "Aircon repaired",
    });
  });

  it("TEST-FE-818 adds a Unit with the Floor and Unit Type from the Settings lists, and Update Unit never sends the Unit number", async () => {
    const client = unitApi();
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "New Unit" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Enter the Unit number."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Choose the floor.")).toBeInTheDocument();
    expect(client.create).not.toHaveBeenCalled();
    const floors = within(dialog).getByLabelText(/^Floor/);
    expect(
      within(floors)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a floor", "1", "2"]);
    expect(
      within(within(dialog).getByLabelText("Unit Type"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Studio", "1 bedroom"]);

    fireEvent.change(within(dialog).getByLabelText(/^Unit number/), {
      target: { value: " u107 " },
    });
    fireEvent.change(floors, { target: { value: "FLOOR-F002" } });
    fireEvent.change(within(dialog).getByLabelText("Unit Type"), {
      target: { value: "ONE_BEDROOM" },
    });
    fireEvent.change(within(dialog).getByLabelText("Size (m²)"), {
      target: { value: "36" },
    });
    fireEvent.change(within(dialog).getByLabelText("View"), {
      target: { value: "VIEW-RIVER" },
    });
    fireEvent.click(within(dialog).getByLabelText("Balcony"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#/units/unit-U107");
    });
    expect(client.create).toHaveBeenCalledWith("property-1", {
      unit_number: "U107",
      floor_item_id: "FLOOR-F002",
      unit_type: "ONE_BEDROOM",
      status: "VACANT",
      size_square_metres: "36.00",
      bedrooms: null,
      bathrooms: null,
      view_item_id: "VIEW-RIVER",
      kitchen_item_id: null,
      notes: null,
      room_feature_ids: ["ROOM_FEATURE-BALCONY"],
    });

    cleanup();
    window.location.hash = "#/units/unit-U201";
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "Update Unit" }));
    const edit = screen.getByRole("dialog");
    expect(edit).toHaveTextContent("Update Unit · U201");
    expect(within(edit).queryByLabelText(/^Unit number/)).toBeNull();
    fireEvent.change(within(edit).getByLabelText("Notes"), {
      target: { value: "Corner Unit" },
    });
    fireEvent.click(within(edit).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Unit U201 updated.")).toBeInTheDocument();
    const [, sent] = vi.mocked(client.update).mock.calls[0] ?? [];
    expect(sent).toMatchObject({
      floor_item_id: "FLOOR-F002",
      unit_type: "STUDIO",
      notes: "Corner Unit",
      room_feature_ids: ["ROOM_FEATURE-BALCONY"],
    });
    expect(sent).not.toHaveProperty("unit_number");
  });
});
