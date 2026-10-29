import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnitInventoryPanel } from "./UnitInventoryPanel";
import {
  UnitApi,
  UnitConflictError,
  UnitInventory,
  UnitSetupItem,
  UnitSetupListKind,
  UnitSetupLists,
} from "./unitClient";

afterEach(cleanup);

function item(
  list_kind: UnitSetupListKind,
  code: string,
  name_en: string,
): UnitSetupItem {
  return {
    item_id: `${list_kind}-${code}`,
    list_kind,
    code,
    name_en,
    name_km: null,
    sort_order: 0,
    removed: false,
    in_use: false,
    version: 1,
    feature_type_item_id: null,
  };
}

const FURNITURE = "ITEM_TYPE-FURNITURE";
const APPLIANCE = "ITEM_TYPE-APPLIANCE";
const BEDROOM = "UNIT_FEATURE-BEDROOM";
const KITCHEN = "UNIT_FEATURE-KITCHEN";

const lists: UnitSetupLists = {
  lists: {
    FLOOR: [],
    UNIT_TYPE: [],
    VIEW: [],
    KITCHEN: [],
    ROOM_FEATURE: [],
    FEATURE_TYPE: [],
    UNIT_FEATURE: [
      item("UNIT_FEATURE", "BEDROOM", "Bedroom"),
      item("UNIT_FEATURE", "KITCHEN", "Kitchen"),
    ],
    ITEM_TYPE: [
      item("ITEM_TYPE", "FURNITURE", "Furniture"),
      item("ITEM_TYPE", "APPLIANCE", "Appliance"),
    ],
  },
  can_manage: true,
};

const features = [
  { item_id: BEDROOM, count: 2 },
  { item_id: KITCHEN, count: 1 },
];

const saved: UnitInventory = {
  unit_id: "unit-1",
  record_number: 2,
  recorded_at: "2026-10-24T05:30:00Z",
  recorded_by: "actor-1",
  lines: [
    {
      item_type_item_id: FURNITURE,
      item_name: "Bed",
      where_item_id: BEDROOM,
      where_number: 2,
      quantity: 1,
    },
    {
      item_type_item_id: FURNITURE,
      item_name: "Dining chair",
      where_item_id: null,
      where_number: null,
      quantity: 4,
    },
    {
      item_type_item_id: APPLIANCE,
      item_name: "Fan",
      where_item_id: null,
      where_number: null,
      quantity: 1,
    },
  ],
  counts: { [FURNITURE]: 5, [APPLIANCE]: 1 },
  can_manage: true,
};

function api(overrides: Partial<UnitApi> = {}): UnitApi {
  return {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    timeline: vi.fn(),
    setupLists: vi.fn(),
    createSetupItem: vi.fn(),
    updateSetupItem: vi.fn(),
    removeSetupItem: vi.fn(),
    inventory: vi.fn().mockResolvedValue(saved),
    saveInventory: vi.fn().mockResolvedValue({ ...saved, record_number: 3 }),
    inventoryItems: vi.fn().mockResolvedValue([
      { item_type_item_id: FURNITURE, item_name: "Bed" },
      { item_type_item_id: APPLIANCE, item_name: "Kettle" },
    ]),
    setRentTerms: vi.fn(),
    setFeatures: vi.fn(),
    ...overrides,
  };
}

function show(client: UnitApi, unitId = "unit-1", onSaved = vi.fn()) {
  return render(
    <UnitInventoryPanel
      api={client}
      features={features}
      lists={lists}
      onSaved={onSaved}
      propertyId="property-1"
      unitId={unitId}
    />,
  );
}

describe("Unit inventory", () => {
  it("TEST-FE-819 shows the count by Item type and each item with its place; Edit inventory changes a line in place, removes one with × and adds one with Where (V1.1, DL-115 (I))", async () => {
    const client = api();
    const onSaved = vi.fn();
    show(client, "unit-1", onSaved);

    expect(
      await screen.findByText(
        "5 furniture · 1 appliance · saved 24/10/2026 12:30",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Dining chair").closest("li")).toHaveTextContent(
      "Dining chair×4",
    );
    expect(screen.getByText("Bed").closest("li")).toHaveTextContent(
      "Bed · Bedroom 2",
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit inventory" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Where is Bed")).toHaveValue(
      `${BEDROOM}:2`,
    );
    // Where offers the Unit's own places: two Bedrooms and one Kitchen.
    expect(
      within(within(dialog).getByLabelText("Where is Bed"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Not set", "Bedroom 1", "Bedroom 2", "Kitchen"]);
    fireEvent.change(within(dialog).getByLabelText("How many Dining chair"), {
      target: { value: "6" },
    });
    fireEvent.click(within(dialog).getByLabelText("Remove Fan"));
    fireEvent.change(within(dialog).getByLabelText("New item type"), {
      target: { value: APPLIANCE },
    });
    fireEvent.change(within(dialog).getByLabelText("New item name"), {
      target: { value: " Kettle " },
    });
    fireEvent.change(within(dialog).getByLabelText("New item: where"), {
      target: { value: `${KITCHEN}:1` },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(within(dialog).getByLabelText("Where is Kettle")).toHaveValue(
      `${KITCHEN}:1`,
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save inventory" }),
    );

    expect(
      await screen.findByText(
        "Parking inventory saved. The earlier list stays in History.",
      ),
    ).toBeInTheDocument();
    expect(client.saveInventory).toHaveBeenCalledWith(saved, [
      saved.lines[0],
      { ...saved.lines[1], quantity: 6 },
      {
        item_type_item_id: APPLIANCE,
        item_name: "Kettle",
        where_item_id: KITCHEN,
        where_number: 1,
        quantity: 1,
      },
    ]);
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("TEST-FE-820 hides Edit inventory without access and names a save someone else beat", async () => {
    show(
      api({
        inventory: vi.fn().mockResolvedValue({
          ...saved,
          lines: [],
          counts: {},
          recorded_at: null,
          record_number: 0,
          can_manage: false,
        }),
      }),
    );
    expect(
      await screen.findByText(
        "No inventory has been recorded for this Parking yet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit inventory" }),
    ).not.toBeInTheDocument();

    cleanup();
    show(
      api({
        saveInventory: vi.fn().mockRejectedValue(new UnitConflictError()),
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit inventory" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Save inventory" }),
    );
    expect(
      await screen.findByText(/Someone else saved this inventory first\./),
    ).toHaveAttribute("role", "status");
    expect(
      screen.getByRole("button", { name: "Edit inventory" }),
    ).toBeEnabled();
  });

  it("TEST-FE-822 refuses an empty name, a wrong count and the same item twice in one place, and loads the new Unit after a switch", async () => {
    const client = api();
    const { rerender } = show(client);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit inventory" }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Enter the new item's name, then Add.",
    );
    fireEvent.change(within(dialog).getByLabelText("How many Fan"), {
      target: { value: "0" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save inventory" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "How many Fan: enter a whole number from 1 to 999.",
    );
    fireEvent.change(within(dialog).getByLabelText("How many Fan"), {
      target: { value: "1" },
    });
    // A second Bed in the same Bedroom 2 is one line, not two.
    fireEvent.change(within(dialog).getByLabelText("New item name"), {
      target: { value: "BED" },
    });
    fireEvent.change(within(dialog).getByLabelText("New item: where"), {
      target: { value: `${BEDROOM}:2` },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save inventory" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "BED is listed twice for the same type and place.",
    );
    expect(client.saveInventory).not.toHaveBeenCalled();

    rerender(
      <UnitInventoryPanel
        api={client}
        features={features}
        lists={lists}
        propertyId="property-1"
        unitId="unit-2"
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Edit inventory" }),
    ).toBeEnabled();
    expect(client.inventory).toHaveBeenLastCalledWith("unit-2");
  });
});
