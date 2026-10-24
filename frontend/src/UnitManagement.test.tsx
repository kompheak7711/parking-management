import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnitManagement } from "./UnitManagement";
import {
  UnitApi,
  UnitConflictError,
  UnitInventory,
  UnitResource,
  UnitSetupItem,
  UnitSetupListKind,
  UnitUnavailableError,
} from "./unitClient";

const unit: UnitResource = {
  unit_id: "unit-1",
  property_id: "property-1",
  unit_number: "101",
  floor: "1",
  floor_item_id: "floor-1",
  unit_type: "STUDIO",
  status: "UNDER_MAINTENANCE",
  version: 2,
  size_square_metres: null,
  bedrooms: null,
  bathrooms: null,
  view_item_id: null,
  kitchen_item_id: null,
  notes: null,
  room_feature_ids: [],
  current_reservation: null,
  current_lease: null,
  current_occupancy: null,
  active_meter_summary: null,
  operational_alerts: ["UNDER_MAINTENANCE"],
  can_manage: true,
};

afterEach(cleanup);

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

const inventory: UnitInventory = {
  unit_id: "unit-1",
  record_number: 0,
  recorded_at: null,
  recorded_by: null,
  lines: [],
  counts: { FURNITURE: 0, APPLIANCES: 0, KITCHEN: 0, BATHROOM: 0 },
  can_manage: true,
};

const setupLists = {
  lists: {
    FLOOR: [
      { ...setupItem("FLOOR", "F001", "1"), item_id: "floor-1" },
      setupItem("FLOOR", "F002", "2"),
      setupItem("FLOOR", "F009", "Old roof", true),
    ],
    UNIT_TYPE: [
      setupItem("UNIT_TYPE", "STUDIO", "Studio"),
      setupItem("UNIT_TYPE", "ONE_BEDROOM", "1 bedroom"),
    ],
    VIEW: [setupItem("VIEW", "RIVER", "River view")],
    KITCHEN: [],
    ROOM_FEATURE: [setupItem("ROOM_FEATURE", "BALCONY", "Balcony")],
  },
  can_manage: false,
};

function api(overrides: Partial<UnitApi> = {}): UnitApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [unit],
      next_cursor: null,
      can_manage: true,
    }),
    get: vi.fn().mockResolvedValue(unit),
    create: vi.fn().mockResolvedValue(unit),
    update: vi
      .fn()
      .mockResolvedValue({ ...unit, status: "CLEANING", version: 3 }),
    setupLists: vi.fn().mockResolvedValue(setupLists),
    createSetupItem: vi.fn(),
    updateSetupItem: vi.fn(),
    removeSetupItem: vi.fn(),
    inventory: vi.fn().mockResolvedValue(inventory),
    saveInventory: vi.fn(),
    inventoryItems: vi.fn().mockResolvedValue([]),
    timeline: vi.fn().mockResolvedValue({
      items: [
        {
          event_id: "event-1",
          occurred_at: "2026-08-24T00:00:00Z",
          actor_id: "actor-1",
          action: "unit.updated",
          entity_type: "unit",
          reason: "Authorized update",
          previous_state: { status: "VACANT" },
          resulting_state: { status: "UNDER_MAINTENANCE" },
          correlation_id: "correlation-1",
          outcome: "SUCCEEDED",
        },
      ],
      next_cursor: null,
    }),
    ...overrides,
  };
}

async function loadUnits(client: UnitApi) {
  render(<UnitManagement api={client} />);
  fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
    target: { value: "property-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load Units" }));
  await screen.findByText("1 Unit record(s) loaded.");
}

describe("Unit management", () => {
  it("TEST-FE-027 shows a semantic Unit table, alerts, and authorized controls", async () => {
    const client = api();
    await loadUnits(client);

    expect(
      screen.getByRole("table", { name: /Current Unit source data/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Status" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("UNDER_MAINTENANCE").length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByRole("heading", { name: "Create Unit" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-028 hides Unit mutations without server capability", async () => {
    const client = api({
      list: vi.fn().mockResolvedValue({
        items: [unit],
        next_cursor: null,
        can_manage: false,
      }),
    });
    await loadUnits(client);

    expect(
      screen.queryByRole("heading", { name: "Create Unit" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-029 separates Unit sources and immutable audit history", async () => {
    const client = api();
    await loadUnits(client);
    fireEvent.click(screen.getByRole("button", { name: "Open Unit 101" }));

    expect(
      await screen.findByRole("heading", { name: "Unit 101 detail" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reservations")).toBeInTheDocument();
    expect(screen.getByText("Leases and Occupancy")).toBeInTheDocument();
    expect(screen.getByText("Meters and Readings")).toBeInTheDocument();
    expect(screen.getByText("Billing history")).toBeInTheDocument();
    expect(screen.getByText("unit.updated")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete/i }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-030 announces Unit authorization and concurrency failures", async () => {
    const denied = api({
      list: vi.fn().mockRejectedValue(new UnitUnavailableError()),
    });
    render(<UnitManagement api={denied} />);
    fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Units" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Unit access is unavailable for this session.",
    );
    expect(
      screen.queryByRole("heading", { name: "Create Unit" }),
    ).not.toBeInTheDocument();

    cleanup();
    const conflicting = api({
      update: vi.fn().mockRejectedValue(new UnitConflictError()),
    });
    await loadUnits(conflicting);
    fireEvent.click(screen.getByRole("button", { name: "Open Unit 101" }));
    await screen.findByRole("heading", { name: "Unit 101 detail" });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Unit source data" }),
    );
    await waitFor(() => {
      expect(screen.getAllByRole("status").at(-1)).toHaveTextContent(
        "The Unit changed. Reload it before retrying.",
      );
    });

    cleanup();
    let resolveCreate!: (created: UnitResource) => void;
    const staleCreate = api({
      create: vi.fn().mockReturnValue(
        new Promise<UnitResource>((resolve) => {
          resolveCreate = resolve;
        }),
      ),
    });
    await loadUnits(staleCreate);
    fireEvent.change(screen.getByLabelText("Unit identifier/name"), {
      target: { value: "102" },
    });
    fireEvent.change(screen.getByLabelText("Floor"), {
      target: { value: "FLOOR-F002" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Unit" }));
    fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
      target: { value: "property-2" },
    });
    act(() => {
      resolveCreate({ ...unit, unit_id: "unit-2", unit_number: "102" });
    });
    expect(
      screen.queryByRole("table", { name: /Current Unit source data/ }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-818 picks the Floor and Unit Type from the Settings lists, keeps the Unit number, and saves the details", async () => {
    const create = vi.fn().mockResolvedValue({
      ...unit,
      unit_id: "unit-2",
      unit_number: "102",
    });
    const update = vi.fn().mockResolvedValue({ ...unit, version: 3 });
    const client = api({ create, update });
    await loadUnits(client);

    const floor = screen.getByLabelText("Floor");
    expect(
      Array.from(floor.querySelectorAll("option")).map((o) => o.textContent),
    ).toEqual(["Choose a Floor", "1", "2"]);
    expect(screen.getByRole("cell", { name: "Studio" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Unit identifier/name"), {
      target: { value: "102" },
    });
    fireEvent.change(floor, { target: { value: "FLOOR-F002" } });
    fireEvent.change(screen.getByLabelText("Unit type"), {
      target: { value: "ONE_BEDROOM" },
    });
    fireEvent.change(screen.getByLabelText("Size (m²)"), {
      target: { value: "42.5" },
    });
    fireEvent.change(screen.getByLabelText("View"), {
      target: { value: "VIEW-RIVER" },
    });
    fireEvent.click(screen.getByLabelText("Balcony"));
    fireEvent.click(screen.getByRole("button", { name: "Create Unit" }));

    await waitFor(() => {
      expect(create).toHaveBeenCalledWith("property-1", {
        unit_number: "102",
        floor_item_id: "FLOOR-F002",
        unit_type: "ONE_BEDROOM",
        status: "VACANT",
        size_square_metres: "42.50",
        bedrooms: null,
        bathrooms: null,
        view_item_id: "VIEW-RIVER",
        kitchen_item_id: null,
        notes: null,
        room_feature_ids: ["ROOM_FEATURE-BALCONY"],
      });
    });

    cleanup();
    const editing = api({ update });
    await loadUnits(editing);
    fireEvent.click(screen.getByRole("button", { name: "Open Unit 101" }));
    await screen.findByRole("heading", { name: "Unit 101 detail" });
    expect(screen.getByText(/cannot\s+change\./)).toBeInTheDocument();
    expect(document.querySelector("#edit-unit-number")).toBeNull();
    fireEvent.change(
      screen.getByLabelText("Bedrooms", { selector: "#edit-unit-bedrooms" }),
      {
        target: { value: "1" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save Unit source data" }),
    );

    await waitFor(() => {
      expect(update).toHaveBeenCalledTimes(1);
    });
    const sent = update.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(sent).not.toHaveProperty("unit_number");
    expect(sent).toMatchObject({
      floor_item_id: "floor-1",
      unit_type: "STUDIO",
      bedrooms: 1,
      size_square_metres: null,
    });

    cleanup();
    render(
      <UnitManagement
        api={api({ setupLists: vi.fn().mockRejectedValue(new Error("down")) })}
      />,
    );
    fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Units" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The Settings lists could not be read",
    );
    expect(
      screen.getByRole("table", { name: /Current Unit source data/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Create Unit" }),
    ).not.toBeInTheDocument();
  });
});
