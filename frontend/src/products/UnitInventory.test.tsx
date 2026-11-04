import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type Catalogue,
  type Locations,
  type Product,
  ProductsError,
  type ProductsApi,
} from "./productsClient";
import { UnitInventoryCard } from "./UnitInventory";

afterEach(() => {
  cleanup();
});

function product(extra: Partial<Product>): Product {
  return {
    product_id: "p-fan",
    sku: "P0001",
    name_en: "Fan",
    name_kh: "កង្ហារ",
    description: null,
    category_code: "APPLIANCES",
    kind: "ITEM",
    measure_unit: "PIECE",
    cost_usd_cents: 2500,
    mark_up_basis_points: 2000,
    min_mark_up_basis_points: 1500,
    max_mark_up_basis_points: null,
    price_usd_cents: 3000,
    real_mark_up_basis_points: 2000,
    reorder_level: null,
    reorder_quantity: null,
    discontinued: false,
    version: 1,
    stock: "3",
    low_stock: false,
    ...extra,
  };
}

const FAN = product({});
const BED = product({
  product_id: "p-bed",
  sku: "P0002",
  name_en: "Bed",
  name_kh: null,
  category_code: "FURNITURE",
  cost_usd_cents: 12000,
  stock: "1",
});
const SOAP = product({
  product_id: "p-soap",
  sku: "P0003",
  name_en: "Soap",
  name_kh: null,
  category_code: "SUPPLIES",
  stock: "9",
});

const CATALOGUE: Catalogue = {
  rules: {
    mark_up_basis_points: 2000,
    min_mark_up_basis_points: 1500,
    max_mark_up_basis_points: null,
    price_round_up_usd_cents: 10,
  },
  categories: [
    { code: "FURNITURE", name_en: "Furniture", name_kh: null, kind: "ITEM" },
    { code: "APPLIANCES", name_en: "Appliances", name_kh: null, kind: "ITEM" },
    { code: "SUPPLIES", name_en: "Supplies", name_kh: null, kind: "ITEM" },
  ],
  products: [FAN, BED, SOAP],
};

const W01 = { unit_id: "unit-w01", item_id: "item-cabinet", number: 1 };
const BEDROOM = { unit_id: "unit-101", item_id: "item-bedroom", number: 1 };
const LIVING = { unit_id: "unit-101", item_id: "item-living", number: 1 };

function line(item: Product, quantity: string) {
  return {
    product_id: item.product_id,
    sku: item.sku,
    name_en: item.name_en,
    measure_unit: item.measure_unit,
    quantity,
  };
}

function locations(unitStock: ReturnType<typeof line>[] = []): Locations {
  return {
    places: [
      {
        ...W01,
        unit_number: "W01",
        for_rent: false,
        name_en: "Cabinet",
        name_kh: null,
        stock: [line(FAN, "2"), line(BED, "1"), line(SOAP, "9")],
      },
      {
        ...BEDROOM,
        unit_number: "U101",
        for_rent: true,
        name_en: "Bedroom",
        name_kh: null,
        stock: unitStock,
      },
      {
        ...LIVING,
        unit_number: "U101",
        for_rent: true,
        name_en: "Living room",
        name_kh: null,
        stock: [],
      },
      {
        unit_id: "unit-102",
        item_id: "item-bedroom",
        number: 1,
        unit_number: "U102",
        for_rent: true,
        name_en: "Bedroom",
        name_kh: null,
        stock: [line(FAN, "4")],
      },
    ],
    features: [],
  };
}

function apiOf(extra: Partial<ProductsApi> = {}) {
  return {
    catalogue: vi.fn(() => Promise.resolve(CATALOGUE)),
    addProduct: vi.fn(() =>
      Promise.resolve({
        ...CATALOGUE,
        products: [
          ...CATALOGUE.products,
          product({
            product_id: "p-chair",
            sku: "P0004",
            name_en: "Chair",
            name_kh: null,
            category_code: "FURNITURE",
            stock: "0",
          }),
        ],
      }),
    ),
    changeProduct: vi.fn(() => Promise.resolve(CATALOGUE)),
    setMarkUps: vi.fn(() => Promise.resolve(CATALOGUE)),
    setServiceCost: vi.fn(() => Promise.resolve(CATALOGUE)),
    prices: vi.fn(() => Promise.resolve([])),
    movements: vi.fn(() => Promise.resolve([])),
    recordMovement: vi.fn(() => Promise.resolve("SM260005")),
    recordMovements: vi.fn(() => Promise.resolve(["SM260003", "SM260004"])),
    locations: vi.fn(() => Promise.resolve(locations())),
    addPlace: vi.fn(() => Promise.resolve(2)),
    ...extra,
  };
}

const STAFF = new Set(["products.read", "stock.purchase", "stock.transfer"]);
const MANAGER = new Set([...STAFF, "products.manage", "stock.adjust"]);

function show(api: ProductsApi, capabilities: ReadonlySet<string>) {
  return render(
    <UnitInventoryCard
      api={api}
      capabilities={capabilities}
      language="en"
      propertyId="property-1"
      unitId="unit-101"
      unitNumber="U101"
    />,
  );
}

function pick(scope: HTMLElement, label: string | RegExp, value: string) {
  fireEvent.change(within(scope).getByLabelText(label), {
    target: { value },
  });
}

const W01_KEY = "unit-w01|item-cabinet|1";
const BEDROOM_KEY = "unit-101|item-bedroom|1";
const LIVING_KEY = "unit-101|item-living|1";

async function openForm() {
  fireEvent.click(
    await screen.findByRole("button", { name: "Unit inventory" }),
  );
  return screen.findByRole("dialog", { name: "Unit inventory: U101" });
}

describe("Unit page › Unit inventory (V1.1 part 5, DL-122)", () => {
  it("TEST-FE-1148 the Unit page counts what is in the Unit from the stock, starts empty, and is hidden without products.read", async () => {
    const empty = apiOf();
    show(empty, STAFF);
    expect(await screen.findByText("Nothing in this Unit yet.")).toBeTruthy();
    expect(empty.locations).toHaveBeenCalledWith("property-1");
    cleanup();

    const full = apiOf({
      locations: vi.fn(() =>
        Promise.resolve({
          ...locations([line(FAN, "2"), line(BED, "1")]),
          places: locations([line(FAN, "2"), line(BED, "1")]).places.map(
            (place) =>
              place.item_id === "item-living" && place.unit_id === "unit-101"
                ? { ...place, stock: [line(FAN, "4")] }
                : place,
          ),
        }),
      ),
    });
    show(full, STAFF);
    expect(await screen.findByText(/7 items in 2 places/)).toBeTruthy();
    cleanup();

    const hidden = apiOf();
    const { container } = show(hidden, new Set(["units.read"]));
    expect(container.textContent).toBe("");
    expect(hidden.locations).not.toHaveBeenCalled();
  });

  it("TEST-FE-1149 the form puts items in from storage row by row, lists only Furniture and Appliances in storage, refuses more than a storage place holds, and saves every row together as Transfers", async () => {
    const api = apiOf();
    show(api, STAFF);
    const form = await openForm();
    // Soap is in storage but is not Furniture or Appliances; U102's fan is not storage.
    const items = within(form).getByLabelText("Item 1");
    expect(items.textContent).toContain("Fan");
    expect(items.textContent).toContain("Bed");
    expect(items.textContent).not.toContain("Soap");
    expect(within(form).queryByLabelText("Item 2")).toBeNull();

    pick(form, "Location 1", BEDROOM_KEY);
    pick(form, "Item 1", "p-bed");
    expect(within(form).getByLabelText("Storage 1").textContent).toContain(
      "W01 · Cabinet 1 (1 here)",
    );
    pick(form, "Storage 1", W01_KEY);
    fireEvent.change(within(form).getByLabelText("Qty 1"), {
      target: { value: "1" },
    });
    // A new row appears when the last one is used.
    pick(form, "Location 2", LIVING_KEY);
    pick(form, "Item 2", "p-fan");
    pick(form, "Storage 2", W01_KEY);
    fireEvent.change(within(form).getByLabelText("Qty 2"), {
      target: { value: "3" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(within(form).getByRole("alert").textContent).toContain(
      "Row 2: only 2 in that storage place",
    );
    expect(api.recordMovements).not.toHaveBeenCalled();

    fireEvent.change(within(form).getByLabelText("Qty 2"), {
      target: { value: "2" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordMovements).toHaveBeenCalledTimes(1);
    });
    expect(api.recordMovements).toHaveBeenCalledWith("property-1", [
      expect.objectContaining({
        kind: "TRANSFER",
        product_id: "p-bed",
        quantity: "1",
        from: W01,
        to: BEDROOM,
      }),
      expect.objectContaining({
        kind: "TRANSFER",
        product_id: "p-fan",
        quantity: "2",
        from: W01,
        to: LIVING,
      }),
    ]);
    expect(await screen.findByText("Bed, Fan moved into U101.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("TEST-FE-1150 New purchase buys into a storage place (Reorder fills the last cost; New product only for a Manager) and goes back to the form with the item already in a row", async () => {
    const api = apiOf();
    show(api, MANAGER);
    let form = await openForm();
    fireEvent.click(within(form).getByRole("button", { name: "New purchase" }));
    let buy = await screen.findByRole("dialog", { name: "New purchase" });
    pick(buy, /^Product/, "p-fan");
    expect(within(buy).getByLabelText(/^Cost of one/)).toHaveProperty(
      "value",
      "25.00",
    );
    fireEvent.change(within(buy).getByLabelText(/^Qty/), {
      target: { value: "1" },
    });
    pick(buy, /^Put in/, W01_KEY);
    fireEvent.click(within(buy).getByRole("button", { name: "Save" }));
    form = await screen.findByRole("dialog", { name: "Unit inventory: U101" });
    expect(api.recordMovement).toHaveBeenCalledWith(
      "property-1",
      expect.objectContaining({
        kind: "PURCHASE",
        product_id: "p-fan",
        quantity: "1",
        to: W01,
        unit_cost_usd_cents: 2500,
      }),
    );
    expect(await screen.findByText("Fan bought.")).toBeTruthy();
    expect(within(form).getByLabelText("Item 1")).toHaveProperty(
      "value",
      "p-fan",
    );
    expect(within(form).getByLabelText("Storage 1")).toHaveProperty(
      "value",
      W01_KEY,
    );
    expect(within(form).getByLabelText("Qty 1")).toHaveProperty("value", "1");

    fireEvent.click(within(form).getByRole("button", { name: "New purchase" }));
    buy = await screen.findByRole("dialog", { name: "New purchase" });
    fireEvent.click(within(buy).getByLabelText("New product"));
    fireEvent.change(within(buy).getByLabelText(/^Name in English/), {
      target: { value: "Chair" },
    });
    pick(buy, "Category", "FURNITURE");
    fireEvent.change(within(buy).getByLabelText(/^Cost of one/), {
      target: { value: "15" },
    });
    pick(buy, /^Put in/, W01_KEY);
    fireEvent.click(within(buy).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordMovement).toHaveBeenCalledTimes(2);
    });
    expect(api.addProduct).toHaveBeenCalledWith(
      "property-1",
      expect.objectContaining({
        name_en: "Chair",
        category_code: "FURNITURE",
        measure_unit: "PIECE",
      }),
    );
    expect(api.recordMovement).toHaveBeenLastCalledWith(
      "property-1",
      expect.objectContaining({
        kind: "PURCHASE",
        product_id: "p-chair",
        unit_cost_usd_cents: 1500,
      }),
    );
    cleanup();

    show(apiOf(), STAFF);
    form = await openForm();
    fireEvent.click(within(form).getByRole("button", { name: "New purchase" }));
    buy = await screen.findByRole("dialog", { name: "New purchase" });
    expect(within(buy).queryByLabelText("New product")).toBeNull();
  });

  it("TEST-FE-1151 Take out sends an item back to storage or records it as Broken or lost (Manager only), always with a reason; a refusal stays in the form", async () => {
    const api = apiOf({
      locations: vi.fn(() => Promise.resolve(locations([line(FAN, "1")]))),
    });
    show(api, STAFF);
    let form = await openForm();
    const now = within(form).getByText("Now in this Unit");
    expect(now).toBeTruthy();
    fireEvent.click(
      within(form).getByRole("button", { name: "Take out: Fan, Bedroom 1" }),
    );
    let take = await screen.findByRole("dialog", { name: "Take out Fan" });
    expect(within(take).getByLabelText(/^Broken or lost/)).toHaveProperty(
      "disabled",
      true,
    );
    pick(take, /^Put in/, W01_KEY);
    fireEvent.click(within(take).getByRole("button", { name: "Save" }));
    expect(within(take).getByRole("alert").textContent).toContain(
      "Enter the reason.",
    );
    fireEvent.change(within(take).getByLabelText(/^Reason/), {
      target: { value: "Tenant moved out" },
    });
    fireEvent.click(within(take).getByRole("button", { name: "Save" }));
    await screen.findByRole("dialog", { name: "Unit inventory: U101" });
    expect(api.recordMovement).toHaveBeenCalledWith(
      "property-1",
      expect.objectContaining({
        kind: "TRANSFER",
        product_id: "p-fan",
        from: BEDROOM,
        to: W01,
        reason: "Tenant moved out",
      }),
    );
    expect(await screen.findByText("Fan taken out.")).toBeTruthy();
    cleanup();

    const refused = apiOf({
      locations: vi.fn(() => Promise.resolve(locations([line(FAN, "1")]))),
      recordMovement: vi.fn(() =>
        Promise.reject(
          new ProductsError(409, "There is not enough stock at this place"),
        ),
      ),
    });
    show(refused, MANAGER);
    form = await openForm();
    fireEvent.click(
      within(form).getByRole("button", { name: "Take out: Fan, Bedroom 1" }),
    );
    take = await screen.findByRole("dialog", { name: "Take out Fan" });
    fireEvent.click(within(take).getByLabelText(/^Broken or lost/));
    expect(within(take).queryByLabelText(/^Put in/)).toBeNull();
    fireEvent.change(within(take).getByLabelText(/^Reason/), {
      target: { value: "Broken" },
    });
    fireEvent.click(within(take).getByRole("button", { name: "Save" }));
    expect((await within(take).findByRole("alert")).textContent).toContain(
      "There is not enough stock at this place",
    );
    expect(refused.recordMovement).toHaveBeenCalledWith(
      "property-1",
      expect.objectContaining({
        kind: "ADJUSTMENT_OUT",
        from: BEDROOM,
        to: null,
        reason: "Broken",
      }),
    );
  });
});
