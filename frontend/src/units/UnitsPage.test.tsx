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
import { HOME_FIELDS, ROOM_FEATURES, UNIT_INVENTORY } from "../leases/parking";
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
import type { UtilityMeter, UtilityRate } from "../utilityClient";
import type { RentTermsServicesApi } from "./RentTerms";
import { UnitsPage } from "./UnitsPage";
import type { UtilityPricesApi } from "./UtilityPrices";

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
    setRentTerms: vi.fn(),
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

const RATES: UtilityRate[] = [
  {
    id: "rate-el-1",
    utility_type: "ELECTRICITY",
    measurement_unit_code: "KWH",
    rate_usd_per_unit: "0.2500",
    effective_date: "2025-01-24",
    notice_at: "2024-12-20T02:00:00Z",
    notice_evidence: "Notice board",
    source_memo: null,
  },
  {
    id: "rate-el-2",
    utility_type: "ELECTRICITY",
    measurement_unit_code: "KWH",
    rate_usd_per_unit: "0.3000",
    effective_date: "2099-01-24",
    notice_at: "2098-12-20T02:00:00Z",
    notice_evidence: "Notice board",
    source_memo: null,
  },
  {
    id: "rate-wa-1",
    utility_type: "WATER",
    measurement_unit_code: "M3",
    rate_usd_per_unit: "0.7500",
    effective_date: "2025-01-24",
    notice_at: "2024-12-20T02:00:00Z",
    notice_evidence: "Notice board",
    source_memo: null,
  },
];

function utilityApi(meters: Partial<UtilityMeter>[] = []): UtilityPricesApi & {
  loadMeters: ReturnType<typeof vi.fn>;
  loadRates: ReturnType<typeof vi.fn>;
} {
  return {
    loadMeters: vi.fn().mockResolvedValue({
      items: meters as UtilityMeter[],
      nextCursor: null,
    }),
    loadRates: vi.fn().mockResolvedValue({ items: RATES, nextCursor: null }),
  };
}

function servicesApi(): RentTermsServicesApi & {
  read: ReturnType<typeof vi.fn>;
} {
  const service = (id: string, name: string, type: string | null = null) => ({
    service_id: id,
    service_code: id,
    name_en: name,
    name_km: null,
    service_type_id: type,
    version: 1,
    rate_today_usd_cents: 1000,
    next_rate: null,
    rates: [],
    approval_periods: [],
    leases_using: 0,
  });
  return {
    read: vi.fn().mockResolvedValue({
      services: [
        service("svc-parking", "Parking", "type-car"),
        {
          ...service("svc-wifi", "Wi-Fi"),
          rate_today_usd_cents: null,
          next_rate: {
            monthly_rate_usd_cents: 800,
            effective_date: "2099-11-01",
          },
        },
      ],
      service_types: [
        {
          service_type_id: "type-car",
          name_en: "Car parking",
          name_km: null,
          one_per_lease: true,
          removed: false,
          version: 1,
        },
      ],
      today: "2026-10-29",
      can_manage: true,
    }),
  };
}

function show(
  client: UnitApi,
  options: {
    leases?: LeaseApi;
    reservations?: ReservationApi;
    capabilities?: ReadonlySet<string> | null;
    utilities?: UtilityPricesApi;
    services?: RentTermsServicesApi;
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
      servicesApi={options.services ?? servicesApi()}
      unitApi={client}
      utilityApi={options.utilities ?? utilityApi()}
    />,
  );
}

function rowOf(number: string): HTMLElement {
  const row = screen.getByRole("link", { name: number }).closest("tr");
  if (row === null) throw new Error(`no row for ${number}`);
  return row;
}

describe("Parking list", () => {
  it("TEST-FE-027 shows the Parking table with status chips, Until from the Lease or Reservation, and New Parking for a manager", async () => {
    show(unitApi());

    expect(
      await screen.findByText("4 Parking at CHETANA Parking"),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Parking", "Floor", "Parking Type", "Status", "Until"]);
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
    expect(screen.getByText("4 Parking")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New Parking" }),
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
    await screen.findByText("4 Parking at CHETANA Parking");

    expect(rowOf("U101")).toHaveTextContent("31/12/2026");
    expect(rowOf("U201")).toHaveTextContent("31/10/2100");
    // Every signed Lease is read, not only the ones running today.
    expect(list).toHaveBeenCalledWith("property-1", { status: "SIGNED" });
  });

  it("TEST-FE-028 hides New Parking, Change status and Update Parking without the server's permission", async () => {
    const client = unitApi({
      list: vi.fn().mockResolvedValue({
        items: units.map((entry) => ({ ...entry, can_manage: false })),
        next_cursor: null,
        can_manage: false,
      }),
      get: vi.fn().mockResolvedValue({ ...u201, can_manage: false }),
    });
    show(client);
    await screen.findByText("4 Parking at CHETANA Parking");
    expect(
      screen.queryByRole("button", { name: "New Parking" }),
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
      screen.queryByRole("button", { name: "Update Parking" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-823 filters by floor, Parking Type and the four count cards", async () => {
    show(unitApi());
    await screen.findByText("4 Parking at CHETANA Parking");
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
    expect(screen.getByText("2 Parking")).toBeInTheDocument();
    expect(card(/^Occupied: 0/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All floors" }));
    fireEvent.change(screen.getByLabelText("Parking Type"), {
      target: { value: "ONE_BEDROOM" },
    });
    expect(screen.getByText("1 Parking")).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Penthouse" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-825 opens a Parking by its address and shows “—” when Leases cannot be read", async () => {
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
        "The Parking could not be read. Retry when the service is available.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("4 Parking at CHETANA Parking");

    window.location.hash = "#/units/unit-U201";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Update Parking" }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }),
    );
    expect(
      await screen.findByText(/Someone else changed this Parking first\./),
    ).toBeInTheDocument();
    // The dialog closes, so the next save starts from the latest details.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(client.get).toHaveBeenCalledTimes(2);
    });
  });
});

describe("Parking page", () => {
  it("TEST-FE-029 keeps the Parking details, Lease, Meters, Invoices and History apart and lists the History", async () => {
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
      screen.getByText(
        HOME_FIELDS
          ? "Floor 1 · Studio · 36 m² · CHETANA Parking"
          : "Floor 1 · Studio · CHETANA Parking",
      ),
    ).toBeInTheDocument();
    for (const name of [
      "Parking details",
      "Current Lease",
      "Lease history",
      "Electricity and water",
      "Invoices for this Parking",
      "History",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    const details = screen
      .getByRole("heading", { name: "Parking details" })
      .closest("section");
    if (details === null) throw new Error("no details card");
    // Parking Step 5: features and home fields are hidden on Parking; the code stays.
    if (ROOM_FEATURES) expect(details).toHaveTextContent("BalconyYes");
    if (HOME_FIELDS) {
      expect(details).toHaveTextContent("ViewRiver view");
      expect(details).toHaveTextContent("KitchenNot recorded");
    }
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
    expect(history).toHaveTextContent("Parking created.");
    for (const link of screen.getAllByRole("link", { name: "Open Lease" })) {
      expect(link).toHaveAttribute("href", "#/leases/lease-1");
    }
  });

  it("TEST-FE-1105 the Parking page shows each Meter with the price in force and the next one, and a kind with no Meter is not billed (V1-061)", async () => {
    window.location.hash = "#/units/unit-U101";
    const utilities = utilityApi([
      {
        id: "meter-1",
        unit_id: "unit-U101",
        utility_type: "ELECTRICITY",
        serial_number: "EL-101",
        current: true,
        deactivated_date: null,
        failure_date: null,
      },
    ]);
    show(unitApi(), { utilities });

    const card = (
      await screen.findByRole("heading", { name: "Electricity and water" })
    ).closest("section");
    if (card === null) throw new Error("no Utilities card");
    await waitFor(() => {
      expect(card).toHaveTextContent("Meter EL-101");
    });
    expect(card).toHaveTextContent("$0.25 per kWh since 24/01/2025");
    expect(card).toHaveTextContent("From 24/01/2099: $0.30 per kWh");
    expect(card).toHaveTextContent("Working");
    expect(card).toHaveTextContent(
      "WaterNo meter, so this Parking is not billed for it.",
    );
    expect(card).not.toHaveTextContent("$0.75");
    expect(utilities.loadMeters).toHaveBeenCalledWith("unit-U101", undefined);
    expect(utilities.loadRates).toHaveBeenCalledWith("property-1", undefined);
  });

  it("TEST-FE-1107 the Parking page shows the default Rent and each required Service by its type and monthly rate, and a Manager changes them in whole cents (V1-061, DL-110)", async () => {
    window.location.hash = "#/units/unit-U103";
    const terms = unit("U103", {
      default_monthly_rent_usd_cents: 45_000,
      required_service_ids: ["svc-parking"],
    });
    const setRentTerms = vi.fn().mockResolvedValue({
      ...terms,
      version: 3,
      default_monthly_rent_usd_cents: 47_550,
      required_service_ids: ["svc-parking", "svc-wifi"],
    });
    const client = unitApi({
      get: vi.fn().mockImplementation(() =>
        Promise.resolve(
          setRentTerms.mock.calls.length === 0
            ? terms
            : {
                ...terms,
                version: 3,
                default_monthly_rent_usd_cents: 47_550,
                required_service_ids: ["svc-parking", "svc-wifi"],
              },
        ),
      ),
      setRentTerms,
    });
    show(client);

    expect(await screen.findByTestId("unit-default-rent")).toHaveTextContent(
      "$450.00",
    );
    await waitFor(() => {
      // The card shows each Service's type and today's monthly rate (owner 29/10/2026).
      expect(screen.getByTestId("unit-required-services")).toHaveTextContent(
        /^Car parking \$10\.00 per month$/,
      );
    });
    const card = screen
      .getByRole("heading", { name: "Rent and Services" })
      .closest("section");
    if (card === null) throw new Error("no Rent and Services card");
    fireEvent.click(within(card).getByRole("button", { name: "Change" }));
    const dialog = await screen.findByRole("dialog");
    const rent = within(dialog).getByLabelText("Default Rent per month");
    fireEvent.change(rent, { target: { value: "475.5x" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "Enter the Rent in dollars and cents above 0, or leave it empty.",
      ),
    ).toBeInTheDocument();
    expect(setRentTerms).not.toHaveBeenCalled();
    fireEvent.change(rent, { target: { value: "475.5" } });
    fireEvent.click(within(dialog).getByLabelText("Wi-Fi"));
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "New price list" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(setRentTerms).toHaveBeenCalledWith(terms, {
        default_monthly_rent_usd_cents: 47_550,
        required_service_ids: ["svc-parking", "svc-wifi"],
        reason: "New price list",
      });
    });
    expect(
      await screen.findByText("The Rent and Services of U103 are saved."),
    ).toBeInTheDocument();
    // A rate that starts later says from when.
    await waitFor(() => {
      expect(screen.getByTestId("unit-required-services")).toHaveTextContent(
        "Car parking $10.00 per month, Wi-Fi $8.00 per month from 01/11/2099",
      );
    });
  });

  it("TEST-FE-1108 a person who may not manage the Parking sees the Rent and Services but cannot change them, and a Parking with none says so (V1-061, DL-110)", async () => {
    window.location.hash = "#/units/unit-U103";
    show(
      unitApi({
        get: vi.fn().mockResolvedValue(unit("U103", { can_manage: false })),
      }),
    );
    expect(await screen.findByTestId("unit-default-rent")).toHaveTextContent(
      "Not set",
    );
    expect(screen.getByTestId("unit-required-services")).toHaveTextContent(
      "None",
    );
    const card = screen
      .getByRole("heading", { name: "Rent and Services" })
      .closest("section");
    if (card === null) throw new Error("no Rent and Services card");
    expect(within(card).queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("TEST-FE-1124 Rent and Services needs a reason before it saves, and sends it trimmed (Parking Step 3: a price change is a money action)", async () => {
    window.location.hash = "#/units/unit-U103";
    const terms = unit("U103", { default_monthly_rent_usd_cents: 35_000 });
    const setRentTerms = vi.fn().mockResolvedValue({
      ...terms,
      version: 3,
      default_monthly_rent_usd_cents: 45_000,
    });
    show(unitApi({ get: vi.fn().mockResolvedValue(terms), setRentTerms }));
    const card = (
      await screen.findByRole("heading", { name: "Rent and Services" })
    ).closest("section");
    if (card === null) throw new Error("no Rent and Services card");
    fireEvent.click(within(card).getByRole("button", { name: "Change" }));
    const dialog = await screen.findByRole("dialog");
    const rent = within(dialog).getByLabelText("Default Rent per month");
    expect(rent).toHaveValue("350.00");
    // The price is as it was: the reason is still needed, but the message says so plainly.
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Give the reason for the change."),
    ).toBeInTheDocument();
    fireEvent.change(rent, { target: { value: "450" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Say why the price changes."),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Reason/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(setRentTerms).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "  New price list  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(setRentTerms).toHaveBeenCalledWith(terms, {
        default_monthly_rent_usd_cents: 45_000,
        required_service_ids: [],
        reason: "New price list",
      });
    });
    expect(
      await screen.findByText("The Rent and Services of U103 are saved."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1125 History shows who changed the price, when, the old and new price and the reason (Parking Step 3)", async () => {
    window.location.hash = "#/units/unit-U103";
    const change = (
      id: string,
      at: string,
      before: number | null,
      after: number | null,
      reason: string,
    ) => ({
      event_id: id,
      occurred_at: at,
      actor_id: "actor-1",
      actor_name: "Sok Dara",
      action: "unit.rent_terms_changed",
      entity_type: "unit",
      reason,
      previous_state: { default_monthly_rent_usd_cents: before },
      resulting_state: { default_monthly_rent_usd_cents: after },
      correlation_id: id,
      outcome: "SUCCEEDED",
    });
    show(
      unitApi({
        timeline: vi.fn().mockResolvedValue({
          items: [
            change(
              "event-3",
              "2026-10-29T03:00:00Z",
              4500,
              4500,
              "Wi-Fi now required",
            ),
            change(
              "event-2",
              "2026-10-28T03:00:00Z",
              3500,
              4500,
              "New price list",
            ),
            change(
              "event-1",
              "2026-10-27T03:00:00Z",
              null,
              3500,
              "Opening price",
            ),
          ],
          next_cursor: null,
        }),
      }),
    );
    const history = (
      await screen.findByRole("heading", { name: "History" })
    ).closest("section");
    if (history === null) throw new Error("no History card");
    const lines = within(history).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent(
      "Rent and Services changed by Sok Dara: Wi-Fi now required29/10/2026 10:00",
    );
    expect(lines[1]).toHaveTextContent(
      "Default monthly price $35.00 → $45.00 by Sok Dara: New price list28/10/2026 10:00",
    );
    expect(lines[2]).toHaveTextContent(
      "Default monthly price Not set → $35.00 by Sok Dara: Opening price",
    );
  });

  it("TEST-FE-1106 the Parking list shows today's Utility prices, and nothing is read without the right to read Utilities (V1-061)", async () => {
    const utilities = utilityApi();
    const view = show(unitApi(), { utilities });
    expect(await screen.findByTestId("utility-prices")).toHaveTextContent(
      "Utility prices now: Electricity $0.25 per kWh · Water $0.75 per m³",
    );
    view.unmount();

    const hidden = utilityApi();
    show(unitApi(), {
      utilities: hidden,
      capabilities: new Set(["units.read"]),
    });
    expect(
      await screen.findByRole("link", { name: "U101" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("utility-prices")).toBeNull();
    expect(hidden.loadRates).not.toHaveBeenCalled();
  });

  it("TEST-FE-1074 each button opens its own place: New Lease opens the form with the Parking chosen or the draft from its Reservation, and Open Lease, Open draft Lease and Open Reservation open that record", async () => {
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

  it("TEST-FE-824 changes the status only with a reason and not while a Lease holds the Parking", async () => {
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
      "This Parking has a signed Lease. Its status changes only through Move-out.",
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

  it("TEST-FE-1121 New Parking takes the default Rent and the required Services and saves them right after the Parking; a wrong amount is refused first (V1-061, DL-110)", async () => {
    const setRentTerms = vi
      .fn()
      .mockResolvedValue(unit("U107", { version: 2 }));
    const client = unitApi({ setRentTerms });
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "New Parking" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Parking number/), {
      target: { value: "U107" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Floor/), {
      target: { value: "FLOOR-F002" },
    });
    const rent = within(dialog).getByLabelText("Default Rent per month");
    fireEvent.change(rent, { target: { value: "350.555" } });
    fireEvent.click(await within(dialog).findByLabelText("Parking"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(rent).toHaveAttribute("aria-invalid", "true");
    expect(client.create).not.toHaveBeenCalled();

    fireEvent.change(rent, { target: { value: "350" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#/units/unit-U107");
    });
    expect(client.create).toHaveBeenCalledTimes(1);
    expect(setRentTerms).toHaveBeenCalledWith(
      expect.objectContaining({ unit_id: "unit-U107" }),
      {
        default_monthly_rent_usd_cents: 35_000,
        required_service_ids: ["svc-parking"],
        reason: "Set with the new Parking",
      },
    );
  });

  it("TEST-FE-1122 when the Parking is saved but its Rent and Services are not, New Parking says so and only closes (V1-061)", async () => {
    const setRentTerms = vi.fn().mockRejectedValue(new Error("offline"));
    const client = unitApi({ setRentTerms });
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "New Parking" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Parking number/), {
      target: { value: "U107" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Floor/), {
      target: { value: "FLOOR-F002" },
    });
    fireEvent.change(within(dialog).getByLabelText("Default Rent per month"), {
      target: { value: "350" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "Parking U107 is saved, but its Rent and Services are not. Set them on the Parking page with Change.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#/units/unit-U107");
    });
    expect(client.create).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-1123 the Parking page offers Add electricity meter and Add water meter for a kind with no meter, set to this Parking (V1-061)", async () => {
    window.location.hash = "#/units/unit-U101";
    const installMeter = vi.fn().mockResolvedValue({
      id: "meter-2",
      unit_id: "unit-U101",
      utility_type: "WATER",
      serial_number: "WA-U101",
      current: true,
      deactivated_date: null,
      failure_date: null,
    });
    const utilities = {
      ...utilityApi([
        {
          id: "meter-1",
          unit_id: "unit-U101",
          utility_type: "ELECTRICITY",
          serial_number: "EL-101",
          current: true,
          deactivated_date: null,
          failure_date: null,
        },
      ]),
      installMeter,
    };
    show(unitApi(), { utilities });
    const card = (
      await screen.findByRole("heading", { name: "Electricity and water" })
    ).closest("section");
    if (card === null) throw new Error("no Utilities card");
    const add = await within(card).findByRole("button", {
      name: "Add water meter",
    });
    expect(
      within(card).queryByRole("button", { name: "Add electricity meter" }),
    ).toBeNull();
    fireEvent.click(add);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Water")).toBeChecked();
    expect(within(dialog).getByLabelText(/^Parking/)).toHaveValue("unit-U101");
    fireEvent.change(within(dialog).getByLabelText(/^Serial/), {
      target: { value: "WA-U101" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    await waitFor(() => {
      expect(installMeter).toHaveBeenCalledTimes(1);
    });
    expect(installMeter.mock.calls[0]?.[0]).toBe("unit-U101");
    expect(installMeter.mock.calls[0]?.[1]).toMatchObject({
      utility_type: "WATER",
      serial_number: "WA-U101",
    });
    expect(
      await within(card).findByText("WA-U101 added to U101."),
    ).toBeInTheDocument();

    cleanup();
    show(unitApi(), {
      capabilities: new Set(["utility.read"]),
      utilities,
    });
    const quiet = (
      await screen.findByRole("heading", { name: "Electricity and water" })
    ).closest("section");
    if (quiet === null) throw new Error("no Utilities card");
    await within(quiet).findByText(/Meter EL-101/);
    expect(within(quiet).queryByRole("button")).toBeNull();
  });

  it("TEST-FE-818 adds a Parking with the Floor and Parking Type from the Settings lists, and Update Parking never sends the Parking number", async () => {
    const client = unitApi();
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "New Parking" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Enter the Parking number."),
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
      within(within(dialog).getByLabelText("Parking Type"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Studio", "1 bedroom"]);

    fireEvent.change(within(dialog).getByLabelText(/^Parking number/), {
      target: { value: " u107 " },
    });
    fireEvent.change(floors, { target: { value: "FLOOR-F002" } });
    fireEvent.change(within(dialog).getByLabelText("Parking Type"), {
      target: { value: "ONE_BEDROOM" },
    });
    // Parking Step 5: the home fields and Room features are hidden on Parking; a hidden field
    // is left out of what is sent. The code stays.
    if (HOME_FIELDS) {
      fireEvent.change(within(dialog).getByLabelText("Size (m²)"), {
        target: { value: "36" },
      });
      fireEvent.change(within(dialog).getByLabelText("View"), {
        target: { value: "VIEW-RIVER" },
      });
    }
    if (ROOM_FEATURES) {
      fireEvent.click(within(dialog).getByLabelText("Balcony"));
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#/units/unit-U107");
    });
    expect(client.create).toHaveBeenCalledWith("property-1", {
      unit_number: "U107",
      floor_item_id: "FLOOR-F002",
      unit_type: "ONE_BEDROOM",
      status: "VACANT",
      notes: null,
      ...(HOME_FIELDS
        ? {
            size_square_metres: "36.00",
            bedrooms: null,
            bathrooms: null,
            view_item_id: "VIEW-RIVER",
            kitchen_item_id: null,
          }
        : {}),
      ...(ROOM_FEATURES ? { room_feature_ids: ["ROOM_FEATURE-BALCONY"] } : {}),
    });

    cleanup();
    window.location.hash = "#/units/unit-U201";
    show(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Update Parking" }),
    );
    const edit = screen.getByRole("dialog");
    expect(edit).toHaveTextContent("Update Parking · U201");
    expect(within(edit).queryByLabelText(/^Parking number/)).toBeNull();
    fireEvent.change(within(edit).getByLabelText("Notes"), {
      target: { value: "Corner Parking" },
    });
    fireEvent.click(within(edit).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Parking U201 updated."),
    ).toBeInTheDocument();
    const [, sent] = vi.mocked(client.update).mock.calls[0] ?? [];
    expect(sent).toMatchObject({
      floor_item_id: "FLOOR-F002",
      unit_type: "STUDIO",
      notes: "Corner Parking",
      ...(ROOM_FEATURES ? { room_feature_ids: ["ROOM_FEATURE-BALCONY"] } : {}),
    });
    expect(sent).not.toHaveProperty("unit_number");
  });
  it("TEST-FE-1139 Parking Step 5: Update Parking leaves the hidden fields out of what it sends, so stored values are kept", async ({
    skip,
  }) => {
    skip(HOME_FIELDS || ROOM_FEATURES);
    const client = unitApi();
    window.location.hash = "#/units/unit-U201";
    show(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Update Parking" }),
    );
    const edit = screen.getByRole("dialog");
    fireEvent.change(within(edit).getByLabelText("Notes"), {
      target: { value: "Near the gate" },
    });
    fireEvent.click(within(edit).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Parking U201 updated."),
    ).toBeInTheDocument();
    const [, sent] = vi.mocked(client.update).mock.calls[0] ?? [];
    expect(sent).toEqual({
      floor_item_id: "FLOOR-F002",
      unit_type: "STUDIO",
      notes: "Near the gate",
    });
  });

  it("TEST-FE-1144 Parking Step 5: the Parking page shows no inventory and no feature tiles, and New Parking has no Room features", async ({
    skip,
  }) => {
    skip(UNIT_INVENTORY || ROOM_FEATURES);
    window.location.hash = "#/units/unit-U101";
    const client = unitApi();
    show(client);
    expect(
      await screen.findByRole("heading", { name: "U101" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Parking inventory" }),
    ).toBeNull();
    expect(client.inventory).not.toHaveBeenCalled();
    const details = screen
      .getByRole("heading", { name: "Parking details" })
      .closest("section");
    if (details === null) throw new Error("no details card");
    expect(details).not.toHaveTextContent("Balcony");
    cleanup();
    window.location.hash = "#/units";
    show(client);
    fireEvent.click(await screen.findByRole("button", { name: "New Parking" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByText("Room features")).toBeNull();
    expect(within(dialog).queryByLabelText("Balcony")).toBeNull();
    expect(dialog).not.toHaveTextContent("empty inventory");
  });

  it("TEST-FE-1146 Parking Step 5: Size, Bedrooms, Bathrooms, View and Kitchen are gone from the dialogs and the Parking page; Floor, Parking Type and Notes stay", async ({
    skip,
  }) => {
    skip(HOME_FIELDS);
    window.location.hash = "#/units/unit-U101";
    const client = unitApi();
    show(client);
    expect(
      await screen.findByRole("heading", { name: "U101" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Floor 1 · Studio · CHETANA Parking"),
    ).toBeInTheDocument();
    const details = screen
      .getByRole("heading", { name: "Parking details" })
      .closest("section");
    if (details === null) throw new Error("no details card");
    expect(details).toHaveTextContent("FloorFloor 1");
    expect(details).toHaveTextContent("Parking TypeStudio");
    for (const gone of ["Size", "Bedrooms", "Bathrooms", "View", "Kitchen"]) {
      expect(within(details).queryByText(gone)).toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: "Update Parking" }));
    const edit = screen.getByRole("dialog");
    expect(within(edit).getByLabelText(/^Floor/)).toBeInTheDocument();
    expect(within(edit).getByLabelText("Parking Type")).toBeInTheDocument();
    expect(within(edit).getByLabelText("Notes")).toBeInTheDocument();
    for (const gone of [
      "Size (m²)",
      "Bedrooms",
      "Bathrooms",
      "View",
      "Kitchen",
    ]) {
      expect(within(edit).queryByLabelText(gone)).toBeNull();
    }
  });
});
