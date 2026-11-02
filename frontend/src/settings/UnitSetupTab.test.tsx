import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UnitConflictError,
  type UnitResource,
  type UnitSetupItem,
  type UnitSetupListKind,
  type UnitSetupLists,
} from "../unitClient";
import { CLEANING_CHARGE, HOME_FIELDS, ROOM_FEATURES } from "../leases/parking";
import { UnitSetupTab } from "./UnitSetupTab";

afterEach(() => {
  cleanup();
});

function item(
  kind: UnitSetupListKind,
  code: string,
  name: string,
  extra: Partial<UnitSetupItem> = {},
): UnitSetupItem {
  return {
    item_id: `${kind}-${code}`,
    list_kind: kind,
    code,
    name_en: name,
    name_km: null,
    sort_order: 0,
    removed: false,
    in_use: false,
    version: 1,
    feature_type_item_id: null,
    ...extra,
  };
}

const LISTS: UnitSetupLists = {
  lists: {
    FLOOR: [
      item("FLOOR", "F1", "Floor 1", { in_use: true, name_km: "ជាន់ទី 1" }),
      item("FLOOR", "F2", "Floor 2"),
    ],
    UNIT_TYPE: [
      item("UNIT_TYPE", "STUDIO", "Studio", { in_use: true }),
      item("UNIT_TYPE", "ONE_BEDROOM", "One Bedroom"),
    ],
    VIEW: [item("VIEW", "STREET", "Street", { in_use: true })],
    KITCHEN: [item("KITCHEN", "KITCHENETTE", "Kitchenette")],
    ROOM_FEATURE: [
      item("ROOM_FEATURE", "BALCONY", "Balcony", { in_use: true }),
    ],
    FEATURE_TYPE: [
      item("FEATURE_TYPE", "ROOM", "Room"),
      item("FEATURE_TYPE", "OUTDOOR", "Outdoor"),
    ],
    UNIT_FEATURE: [
      item("UNIT_FEATURE", "BEDROOM", "Bedroom", {
        feature_type_item_id: "FEATURE_TYPE-ROOM",
      }),
      item("UNIT_FEATURE", "TERRACE", "Terrace", {
        feature_type_item_id: "FEATURE_TYPE-OUTDOOR",
      }),
    ],
    ITEM_TYPE: [item("ITEM_TYPE", "KEYS", "Keys and remotes")],
  },
  can_manage: true,
};

function unit(no: string, extra: Partial<UnitResource> = {}): UnitResource {
  return {
    unit_id: `unit-${no}`,
    property_id: "property-1",
    unit_number: no,
    floor: "1",
    floor_item_id: "FLOOR-F1",
    unit_type: "STUDIO",
    status: "VACANT",
    version: 1,
    current_reservation: null,
    current_lease: null,
    current_occupancy: null,
    active_meter_summary: null,
    operational_alerts: [],
    size_square_metres: null,
    bedrooms: null,
    bathrooms: null,
    view_item_id: "VIEW-STREET",
    kitchen_item_id: null,
    notes: null,
    room_feature_ids: ["ROOM_FEATURE-BALCONY"],
    features: [{ item_id: "UNIT_FEATURE-BEDROOM", count: 2 }],
    ...extra,
  };
}

function apiOf(
  lists: () => Promise<UnitSetupLists> = () => Promise.resolve(LISTS),
) {
  return {
    list: vi.fn(() =>
      Promise.resolve({
        items: [unit("U101"), unit("U102", { room_feature_ids: [] })],
        next_cursor: null,
        can_manage: true,
      }),
    ),
    setupLists: vi.fn(lists),
    createSetupItem: vi.fn((_: string, source: Partial<UnitSetupItem>) =>
      Promise.resolve(item("VIEW", "X", source.name_en ?? "")),
    ),
    updateSetupItem: vi.fn((current: UnitSetupItem) =>
      Promise.resolve(current),
    ),
    removeSetupItem: vi.fn((current: UnitSetupItem) =>
      Promise.resolve({ ...current, removed: true }),
    ),
  };
}

/** The move-out cleaning rates: every Unit Type has one unless named in `noRate`. */
function cleaningOf(noRate: string[] = []) {
  return {
    read: vi.fn(() =>
      Promise.resolve({
        cleaning_rates: [],
        unit_types: LISTS.lists.UNIT_TYPE.map((type) => ({
          code: type.code,
          name_en: type.name_en,
          name_km: type.name_km,
          units: 0,
          cleaning_rate_id: noRate.includes(type.code) ? null : "rate-1",
        })),
        can_manage: true,
      }),
    ),
    add: vi.fn(() => Promise.resolve({})),
    change: vi.fn(() => Promise.resolve({})),
    remove: vi.fn(() => Promise.resolve({})),
  };
}

function show(
  api = apiOf(),
  language: "en" | "km" = "en",
  cleaning = cleaningOf(),
) {
  render(
    <UnitSetupTab
      active
      api={api}
      cleaning={cleaning}
      language={language}
      propertyId="property-1"
    />,
  );
  return api;
}

const list = (name: string) => screen.getByRole("region", { name });

/** V1.1 rework part 1: the lists are tabs; one list shows at a time. */
async function openTab(name: string) {
  fireEvent.click(await screen.findByRole("button", { name, pressed: false }));
  return screen.findByRole("region", { name });
}

describe("Settings: Unit setup", () => {
  it("TEST-FE-940 shows the lists as tabs Floors, Unit Types, Unit features and Views with how many Units use each item; an item in use offers no Remove; Floors have no Edit (V1.1 rework part 1: no Feature types or Item types)", async () => {
    const api = show();
    const floors = await screen.findByRole("region", { name: "Floors" });
    expect(api.setupLists).toHaveBeenCalledWith("property-1");
    const tabs = within(
      screen.getByRole("group", { name: "Unit setup lists" }),
    ).getAllByRole("button");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Floors",
      "Unit Types",
      "Unit features",
      "Views",
    ]);
    expect(tabs[0]?.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByRole("region")).toHaveLength(1);
    for (const gone of [
      "Kitchens",
      "Room features",
      "Feature types",
      "Item types",
    ]) {
      expect(screen.queryByRole("button", { name: gone })).toBeNull();
    }
    const [first, second] = within(floors).getAllByRole("listitem");
    if (first === undefined || second === undefined) throw new Error("rows");
    const rows = [first, second];
    expect(rows[0]?.textContent).toContain("Floor 12 Parking");
    expect(within(first).queryByRole("button")).toBeNull();
    expect(
      within(second).getByRole("button", {
        name: "Remove: Floor 2",
      }),
    ).toBeTruthy();
    expect(rows[1]?.textContent).toContain("No Units yet");

    const features = await openTab("Unit features");
    const [header, bedroom, terrace] = within(features).getAllByRole("row");
    expect(
      within(header ?? features)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Order", "Name", "Khmer", "Units", "Edit"]);
    expect(
      within(bedroom ?? features)
        .getAllByRole("cell")
        .slice(0, 4)
        .map((cell) => cell.textContent),
    ).toEqual(["1", "Bedroom", "", "2"]);
    expect(terrace?.textContent).toContain("Terrace");
    // The type a feature had before is not shown any more.
    expect(features.textContent).not.toContain("Outdoor");
    expect(
      within(features).queryByRole("button", { name: "Remove: Bedroom" }),
    ).toBeNull();
    expect(
      within(features).getByRole("button", { name: "Remove: Terrace" }),
    ).toBeTruthy();
    expect(features.textContent).toContain("A Unit feature is always a place");

    const types = await openTab("Unit Types");
    expect(
      within(types).getByRole("button", { name: "Edit: Studio" }),
    ).toBeTruthy();
    expect(types.textContent).toContain(
      "Rename keeps every Unit of this type.",
    );
    expect(list("Unit Types")).toBe(types);
  });

  it("TEST-FE-941 Add asks a name (and checks it is not in the list yet), a Floor asks its number; Edit renames; Remove asks first; the lists are read again", async () => {
    // Parking Step 5: Views and Kitchens are hidden on Parking, so Add is tried on the
    // Parking Types and Remove on a Parking Type; the code stays.
    const add = HOME_FIELDS
      ? { list: "Views", one: "View", taken: "street", kind: "VIEW" }
      : {
          list: "Parking Types",
          one: "Parking Type",
          taken: "studio",
          kind: "UNIT_TYPE",
        };
    const api = show();
    await openTab("Views");
    fireEvent.click(screen.getByRole("button", { name: "Add: View" }));
    let dialog = screen.getByRole("dialog", { name: "Add · View" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: add.taken },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText(`"${add.taken}" is already in the list.`),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: " Courtyard " },
    });
    fireEvent.change(within(dialog).getByLabelText("Name in Khmer"), {
      target: { value: "ទីធ្លា" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(api.createSetupItem).toHaveBeenCalledWith("property-1", {
      list_kind: add.kind,
      name_en: "Courtyard",
      name_km: "ទីធ្លា",
    });
    expect(api.setupLists).toHaveBeenCalledTimes(2);

    await openTab("Floors");
    fireEvent.click(screen.getByRole("button", { name: "Add: Floor" }));
    dialog = screen.getByRole("dialog", { name: "Add · Floor" });
    fireEvent.change(within(dialog).getByLabelText("Floor number"), {
      target: { value: "1" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText('"Floor 1" is already in the list.'),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Floor number"), {
      target: { value: "120" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Enter a floor number from 0 to 99."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Floor number"), {
      target: { value: "3" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(api.createSetupItem).toHaveBeenLastCalledWith("property-1", {
      list_kind: "FLOOR",
      name_en: "Floor 3",
      name_km: "ជាន់ទី 3",
      sort_order: 30,
    });

    await openTab("Unit Types");
    fireEvent.click(screen.getByRole("button", { name: "Edit: One Bedroom" }));
    dialog = screen.getByRole("dialog", { name: "Edit · Parking Type" });
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: "One Bedroom Deluxe" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(api.updateSetupItem).toHaveBeenCalledWith(LISTS.lists.UNIT_TYPE[1], {
      name_en: "One Bedroom Deluxe",
      name_km: null,
    });

    await openTab("Unit features");
    fireEvent.click(screen.getByRole("button", { name: "Remove: Terrace" }));
    dialog = screen.getByRole("dialog", { name: "Remove · Terrace" });
    expect(dialog.textContent).toContain(
      "Remove Terrace? This cannot be undone. Records made before keep it.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Terrace removed.")).toBeTruthy();
    expect(api.removeSetupItem).toHaveBeenCalledWith(
      LISTS.lists.UNIT_FEATURE[1],
    );
  });

  it("TEST-FE-1124 a Unit feature is added and renamed with no Feature type (V1.1 rework part 1)", async () => {
    const api = show();
    await openTab("Unit features");
    fireEvent.click(screen.getByRole("button", { name: "Add: Unit feature" }));
    let dialog = screen.getByRole("dialog", { name: "Add · Unit feature" });
    expect(within(dialog).queryByLabelText(/Feature type/)).toBeNull();
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: "Cabinet" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(api.createSetupItem).toHaveBeenCalledWith("property-1", {
      list_kind: "UNIT_FEATURE",
      name_en: "Cabinet",
      name_km: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit: Terrace" }));
    dialog = screen.getByRole("dialog", { name: "Edit · Unit feature" });
    expect(within(dialog).queryByLabelText(/Feature type/)).toBeNull();
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: "Pallet Racking" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    // The type kept from before is not sent, so it stays as it was.
    expect(api.updateSetupItem).toHaveBeenCalledWith(
      LISTS.lists.UNIT_FEATURE[1],
      { name_en: "Pallet Racking", name_km: null },
    );
  });

  it("TEST-FE-942 a change refused because the list changed says so and reads again; without the right to change, the lists show with no buttons; a failed read offers Retry", async () => {
    const api = apiOf();
    api.removeSetupItem.mockRejectedValueOnce(new UnitConflictError());
    show(api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove: Floor 2" }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Remove",
      }),
    );
    expect(
      await screen.findByText(
        "Someone changed this list, or a Parking now uses the item. The lists were read again; check and try again.",
      ),
    ).toBeTruthy();
    expect(api.setupLists).toHaveBeenCalledTimes(2);
    // The form held the old version, so it closed; a second try starts from the new lists.
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove: Floor 2" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Remove",
      }),
    );
    expect(await screen.findByText("Floor 2 removed.")).toBeTruthy();
    expect(api.removeSetupItem).toHaveBeenCalledTimes(2);
    cleanup();

    // A Floor moved over from the old Unit records is named by its number alone.
    const moved = apiOf(() =>
      Promise.resolve({
        ...LISTS,
        lists: { ...LISTS.lists, FLOOR: [item("FLOOR", "F003", "3")] },
      }),
    );
    show(moved);
    fireEvent.click(await screen.findByRole("button", { name: "Add: Floor" }));
    fireEvent.change(screen.getByLabelText("Floor number"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText('"Floor 3" is already in the list.')).toBeTruthy();
    expect(moved.createSetupItem).not.toHaveBeenCalled();
    cleanup();

    show(apiOf(() => Promise.resolve({ ...LISTS, can_manage: false })));
    await screen.findByRole("region", { name: "Floors" });
    // Only the four list tabs are buttons.
    expect(screen.queryAllByRole("button")).toHaveLength(4);
    await openTab("Unit features");
    expect(screen.queryAllByRole("button")).toHaveLength(4);
    expect(
      screen.getByText(
        "You can read these lists. Only the Owner or a user the Owner allows can change them.",
      ),
    ).toBeTruthy();
    cleanup();

    let fail = true;
    const flaky = apiOf(() =>
      fail ? Promise.reject(new Error("down")) : Promise.resolve(LISTS),
    );
    show(flaky);
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("region", { name: "Floors" })).toBeTruthy();
  });

  it("TEST-FE-943 Khmer shows the Khmer list names and the mock-up words; without the Parking list an item shows only that a Parking uses it", async () => {
    const api = apiOf();
    api.list.mockRejectedValue(new Error("no units.read"));
    show(api, "km");
    const floors = await screen.findByRole("region", { name: "ជាន់" });
    expect(floors.textContent).toContain("ជាន់ទី 1");
    expect(floors.textContent).toContain("ចំណតកំពុងប្រើ");
    expect(floors.textContent).toContain("មិនទាន់មានចំណត");
  });

  it("TEST-FE-1006 a Parking Type with no move-out cleaning rate shows a No cleaning rate chip; when the rates cannot be read no chip shows", async ({
    skip,
  }) => {
    // Parking Step 5: no cleaning charge on Parking (CLEANING_CHARGE); the code stays.
    skip(!CLEANING_CHARGE);
    show(apiOf(), "en", cleaningOf(["ONE_BEDROOM"]));
    const types = await openTab("Unit Types");
    const one = within(types).getByText("One Bedroom").closest("li");
    await within(one ?? types).findByText("No cleaning rate");
    const studio = within(types).getByText("Studio").closest("li");
    expect(within(studio ?? types).queryByText("No cleaning rate")).toBeNull();
    cleanup();
    const failing = cleaningOf(["ONE_BEDROOM"]);
    failing.read.mockImplementation(() => Promise.reject(new Error("down")));
    show(apiOf(), "en", failing);
    const again = await openTab("Unit Types");
    expect(within(again).queryByText("No cleaning rate")).toBeNull();
  });
  it("TEST-FE-1145 Parking Step 5: the tab shows Floors and Parking Types only; Views, Kitchens and Room features are hidden", async ({
    skip,
  }) => {
    skip(HOME_FIELDS || ROOM_FEATURES);
    show();
    await screen.findByRole("region", { name: "Floors" });
    expect(screen.getByRole("region", { name: "Parking Types" })).toBeTruthy();
    for (const name of ["Views", "Kitchens", "Room features"]) {
      expect(screen.queryByRole("region", { name })).toBeNull();
    }
  });

  it("TEST-FE-1148 Parking Step 5: no cleaning rate chip on a Parking Type, and the cleaning rates are not read", async ({
    skip,
  }) => {
    skip(CLEANING_CHARGE);
    const cleaning = cleaningOf(["STUDIO", "ONE_BEDROOM"]);
    show(apiOf(), "en", cleaning);
    const types = await screen.findByRole("region", { name: "Parking Types" });
    expect(types.textContent).toContain("Studio");
    expect(within(types).queryByText("No cleaning rate")).toBeNull();
    expect(cleaning.read).not.toHaveBeenCalled();
    expect(types.textContent).not.toContain("cleaning rate");
  });
});
