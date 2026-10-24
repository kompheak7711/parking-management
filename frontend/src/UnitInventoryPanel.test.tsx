import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnitInventoryPanel } from "./UnitInventoryPanel";
import { UnitApi, UnitConflictError, UnitInventory } from "./unitClient";

afterEach(cleanup);

const saved: UnitInventory = {
  unit_id: "unit-1",
  record_number: 2,
  recorded_at: "2026-10-24T05:30:00Z",
  recorded_by: "actor-1",
  lines: [
    { item_group: "FURNITURE", item_name: "Bed", quantity: 1 },
    { item_group: "FURNITURE", item_name: "Dining chair", quantity: 4 },
    { item_group: "APPLIANCES", item_name: "Fan", quantity: 1 },
  ],
  counts: { FURNITURE: 5, APPLIANCES: 1, KITCHEN: 0, BATHROOM: 0 },
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
      { item_group: "FURNITURE", item_name: "Bed" },
      { item_group: "KITCHEN", item_name: "Kettle" },
    ]),
    ...overrides,
  };
}

describe("Unit inventory", () => {
  it("TEST-FE-819 shows the count line and items, and Edit inventory saves every item with a number above 0", async () => {
    const client = api();
    const onSaved = vi.fn();
    render(
      <UnitInventoryPanel
        api={client}
        onSaved={onSaved}
        propertyId="property-1"
        unitId="unit-1"
      />,
    );

    expect(
      await screen.findByText(
        "5 furniture items · 1 appliances · 0 kitchen items · 0 bathroom items · saved 24/10/2026 12:30",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Dining chair ×4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit inventory" }));
    const fan = await screen.findByLabelText("Fan");
    expect(fan).toHaveValue(1);
    expect(screen.getByLabelText("Kettle")).toHaveValue(0);
    fireEvent.change(fan, { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Bed"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Kettle"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText("Group"), {
      target: { value: "BATHROOM" },
    });
    fireEvent.change(screen.getByLabelText("Item name"), {
      target: { value: " Hair dryer " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save inventory" }));

    expect(
      await screen.findByText(
        "Unit inventory saved. The earlier list stays in History.",
      ),
    ).toBeInTheDocument();
    expect(client.saveInventory).toHaveBeenCalledWith(saved, [
      { item_group: "FURNITURE", item_name: "Bed", quantity: 1 },
      { item_group: "FURNITURE", item_name: "Dining chair", quantity: 4 },
      { item_group: "KITCHEN", item_name: "Kettle", quantity: 1 },
      { item_group: "BATHROOM", item_name: "Hair dryer", quantity: 1 },
    ]);
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("TEST-FE-820 hides Edit inventory without access and names a save someone else beat", async () => {
    render(
      <UnitInventoryPanel
        api={api({
          inventory: vi.fn().mockResolvedValue({
            ...saved,
            lines: [],
            counts: { FURNITURE: 0, APPLIANCES: 0, KITCHEN: 0, BATHROOM: 0 },
            recorded_at: null,
            record_number: 0,
            can_manage: false,
          }),
        })}
        propertyId="property-1"
        unitId="unit-1"
      />,
    );
    expect(
      await screen.findByText(
        "No inventory has been recorded for this Unit yet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit inventory" }),
    ).not.toBeInTheDocument();

    cleanup();
    render(
      <UnitInventoryPanel
        api={api({
          saveInventory: vi.fn().mockRejectedValue(new UnitConflictError()),
        })}
        propertyId="property-1"
        unitId="unit-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit inventory" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Save inventory" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Someone else saved this inventory first.",
    );
    expect(
      screen.getByRole("button", { name: "Edit inventory" }),
    ).toBeEnabled();
  });

  it("TEST-FE-822 adds an Another item that is already listed to that item and loads the new Unit after a switch", async () => {
    const client = api();
    const { rerender } = render(
      <UnitInventoryPanel
        api={client}
        propertyId="property-1"
        unitId="unit-1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit inventory" }),
    );
    await screen.findByLabelText("Bed");
    fireEvent.change(screen.getByLabelText("Item name"), {
      target: { value: "BED" },
    });
    fireEvent.change(screen.getByLabelText("How many"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save inventory" }));
    await screen.findByText(
      "Unit inventory saved. The earlier list stays in History.",
    );
    expect(client.saveInventory).toHaveBeenCalledWith(saved, [
      { item_group: "FURNITURE", item_name: "Bed", quantity: 3 },
      { item_group: "FURNITURE", item_name: "Dining chair", quantity: 4 },
      { item_group: "APPLIANCES", item_name: "Fan", quantity: 1 },
    ]);

    rerender(
      <UnitInventoryPanel
        api={client}
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
