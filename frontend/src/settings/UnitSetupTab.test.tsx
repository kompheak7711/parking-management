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

function show(api = apiOf(), language: "en" | "km" = "en") {
  render(
    <UnitSetupTab
      active
      api={api}
      language={language}
      propertyId="property-1"
    />,
  );
  return api;
}

const list = (name: string) => screen.getByRole("region", { name });

describe("Settings: Unit setup", () => {
  it("TEST-FE-940 shows the five lists with how many Units use each item; an item in use offers no Remove; Floors have no Edit", async () => {
    const api = show();
    const floors = await screen.findByRole("region", { name: "Floors" });
    expect(api.setupLists).toHaveBeenCalledWith("property-1");
    expect(
      ["Floors", "Unit Types", "Views", "Kitchens", "Room features"].map(
        (name) => list(name).querySelector("h2")?.textContent,
      ),
    ).toEqual(["Floors", "Unit Types", "Views", "Kitchens", "Room features"]);
    const [first, second] = within(floors).getAllByRole("listitem");
    if (first === undefined || second === undefined) throw new Error("rows");
    const rows = [first, second];
    expect(rows[0]?.textContent).toContain("Floor 12 Units");
    expect(within(first).queryByRole("button")).toBeNull();
    expect(
      within(second).getByRole("button", {
        name: "Remove: Floor 2",
      }),
    ).toBeTruthy();
    expect(rows[1]?.textContent).toContain("No Units yet");
    expect(list("Room features").textContent).toContain("Balcony1 Unit");
    expect(
      within(list("Unit Types")).getByRole("button", { name: "Edit: Studio" }),
    ).toBeTruthy();
    expect(list("Unit Types").textContent).toContain(
      "Rename keeps every Unit of this type.",
    );
  });

  it("TEST-FE-941 Add asks a name (and checks it is not in the list yet), a Floor asks its number; Edit renames; Remove asks first; the lists are read again", async () => {
    const api = show();
    await screen.findByRole("region", { name: "Views" });
    fireEvent.click(screen.getByRole("button", { name: "Add: View" }));
    let dialog = screen.getByRole("dialog", { name: "Add · View" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: "street" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText('"street" is already in the list.'),
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
      list_kind: "VIEW",
      name_en: "Courtyard",
      name_km: "ទីធ្លា",
    });
    expect(api.setupLists).toHaveBeenCalledTimes(2);

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

    fireEvent.click(screen.getByRole("button", { name: "Edit: One Bedroom" }));
    dialog = screen.getByRole("dialog", { name: "Edit · Unit Type" });
    fireEvent.change(within(dialog).getByLabelText(/Name in English/), {
      target: { value: "One Bedroom Deluxe" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(api.updateSetupItem).toHaveBeenCalledWith(LISTS.lists.UNIT_TYPE[1], {
      name_en: "One Bedroom Deluxe",
      name_km: null,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Remove: Kitchenette" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Kitchenette" });
    expect(dialog.textContent).toContain(
      "Remove Kitchenette? This cannot be undone. Records made before keep it.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Kitchenette removed.")).toBeTruthy();
    expect(api.removeSetupItem).toHaveBeenCalledWith(LISTS.lists.KITCHEN[0]);
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
        "Someone changed this list, or a Unit now uses the item. The lists were read again; check and try again.",
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
    expect(screen.queryAllByRole("button")).toHaveLength(0);
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

  it("TEST-FE-943 Khmer shows the Khmer list names and the mock-up words; without the Units list an item shows only that a Unit uses it", async () => {
    const api = apiOf();
    api.list.mockRejectedValue(new Error("no units.read"));
    show(api, "km");
    const floors = await screen.findByRole("region", { name: "ជាន់" });
    expect(floors.textContent).toContain("ជាន់ទី 1");
    expect(floors.textContent).toContain("បន្ទប់កំពុងប្រើ");
    expect(floors.textContent).toContain("មិនទាន់មានបន្ទប់");
  });
});
