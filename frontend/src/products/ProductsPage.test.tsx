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
  type Movement,
  type Product,
  ProductsError,
  type ProductsApi,
  priceFor,
  quantityFromText,
} from "./productsClient";
import { ProductsPage, type ProductsTab } from "./ProductsPage";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "#/");
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
    cost_usd_cents: 1000,
    mark_up_basis_points: 2000,
    min_mark_up_basis_points: 1500,
    max_mark_up_basis_points: null,
    price_usd_cents: 1200,
    real_mark_up_basis_points: 2000,
    reorder_level: 2,
    reorder_quantity: 5,
    discontinued: false,
    version: 3,
    stock: "3",
    low_stock: false,
    ...extra,
  };
}

const FAN = product({});
const KETTLE = product({
  product_id: "p-kettle",
  sku: "P0002",
  name_en: "Kettle",
  name_kh: null,
  stock: "1",
  low_stock: true,
});
const OLD = product({
  product_id: "p-old",
  sku: "P0003",
  name_en: "Old lamp",
  name_kh: null,
  discontinued: true,
  stock: "2",
});
const CLEANING = product({
  product_id: "p-clean",
  sku: "P0004",
  name_en: "Room cleaning",
  name_kh: null,
  category_code: "SERVICES",
  kind: "SERVICE",
  measure_unit: "TIME",
  cost_usd_cents: 333,
  price_usd_cents: 400,
  reorder_level: null,
  reorder_quantity: null,
  stock: "0",
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
    {
      code: "APPLIANCES",
      name_en: "Appliances",
      name_kh: "ឧបករណ៍",
      kind: "ITEM",
    },
    { code: "SERVICES", name_en: "Services", name_kh: null, kind: "SERVICE" },
  ],
  products: [FAN, KETTLE, OLD, CLEANING],
};

const CABINET = "item-cabinet";
const BEDROOM = "item-bedroom";
const LOCATIONS: Locations = {
  places: [
    {
      unit_id: "unit-w01",
      unit_number: "W01",
      for_rent: false,
      item_id: CABINET,
      name_en: "Cabinet",
      name_kh: "ទូ",
      number: 1,
      stock: [
        {
          product_id: "p-fan",
          sku: "P0001",
          name_en: "Fan",
          measure_unit: "PIECE",
          quantity: "2",
        },
        {
          product_id: "p-old",
          sku: "P0003",
          name_en: "Old lamp",
          measure_unit: "PIECE",
          quantity: "2",
        },
      ],
    },
    {
      unit_id: "unit-w01",
      unit_number: "W01",
      for_rent: false,
      item_id: CABINET,
      name_en: "Cabinet",
      name_kh: "ទូ",
      number: 2,
      stock: [],
    },
    {
      unit_id: "unit-101",
      unit_number: "U101",
      for_rent: true,
      item_id: BEDROOM,
      name_en: "Bedroom",
      name_kh: null,
      number: 1,
      stock: [
        {
          product_id: "p-fan",
          sku: "P0001",
          name_en: "Fan",
          measure_unit: "PIECE",
          quantity: "1",
        },
      ],
    },
    {
      unit_id: "unit-102",
      unit_number: "U102",
      for_rent: true,
      item_id: BEDROOM,
      name_en: "Bedroom",
      name_kh: null,
      number: 1,
      stock: [],
    },
  ],
  features: [
    { item_id: CABINET, name_en: "Cabinet", name_kh: "ទូ" },
    { item_id: BEDROOM, name_en: "Bedroom", name_kh: null },
  ],
};

const MOVEMENT: Movement = {
  movement_number: "SM260001",
  kind: "PURCHASE",
  product_id: "p-fan",
  sku: "P0001",
  product_name_en: "Fan",
  measure_unit: "PIECE",
  quantity: "3",
  unit_id: "unit-w01",
  unit_number: "W01",
  place_item_id: CABINET,
  place_name_en: "Cabinet",
  place_name_kh: "ទូ",
  place_number: 1,
  unit_cost_usd_cents: 1000,
  supplier: "Market",
  receipt_reference: "R-1",
  reason: null,
  business_date: "2026-11-03",
  recorded_at: "2026-11-03T03:00:00Z",
  recorded_by_name: "Vanna",
};

function apiOf(extra: Partial<ProductsApi> = {}) {
  return {
    catalogue: vi.fn(() => Promise.resolve(CATALOGUE)),
    addProduct: vi.fn(() => Promise.resolve(CATALOGUE)),
    changeProduct: vi.fn(() => Promise.resolve(CATALOGUE)),
    setMarkUps: vi.fn(() => Promise.resolve(CATALOGUE)),
    setServiceCost: vi.fn(() => Promise.resolve(CATALOGUE)),
    prices: vi.fn(() =>
      Promise.resolve([
        {
          price_usd_cents: 1200,
          cost_usd_cents: 1000,
          mark_up_basis_points: 2000,
          cause: "PURCHASE" as const,
          created_at: "2026-11-03T03:00:00Z",
          created_by_name: "Vanna",
        },
      ]),
    ),
    movements: vi.fn(() => Promise.resolve([MOVEMENT])),
    recordMovement: vi.fn(() => Promise.resolve("SM260002")),
    recordMovements: vi.fn(() => Promise.resolve(["SM260003", "SM260004"])),
    locations: vi.fn(() => Promise.resolve(LOCATIONS)),
    addPlace: vi.fn(() => Promise.resolve(3)),
    ...extra,
  };
}

const STAFF = new Set(["products.read", "stock.purchase", "stock.transfer"]);
const MANAGER = new Set([...STAFF, "products.manage", "stock.adjust"]);
const OWNER = new Set([...MANAGER, "products.prices"]);

function show(
  tab: ProductsTab,
  api: ProductsApi,
  capabilities: ReadonlySet<string>,
  language: "en" | "km" = "en",
) {
  return render(
    <ProductsPage
      active
      api={api}
      capabilities={capabilities}
      language={language}
      propertyId="property-1"
      tab={tab}
    />,
  );
}

// Property fix 1 (owner 14/11/2026): a product's Edit, Mark-up, Cost and Prices buttons sit
// in its one "Edit" menu, so a test opens that menu first.
async function openEdit(scope: HTMLElement, name: string) {
  const summary = within(scope).getByLabelText(`Edit: ${name}`);
  fireEvent.click(summary);
  await waitFor(() => {
    expect(
      summary.closest("details")?.querySelector(".ui-rowmenu-list"),
    ).not.toBeNull();
  });
}

function change(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("Building › Products (V1.1 part 4, DL-121)", () => {
  it("TEST-FE-1143 the Products tab shows the price rules, each product's stock, cost, mark-up and price with Low stock and Discontinued, and only the buttons the person's rights allow", async () => {
    const api = apiOf();
    show("products", api, STAFF);
    const table = await screen.findByRole("region", { name: "Products" });
    expect(
      within(table).getByText(
        "New products get a mark-up of 20% (minimum 15%, maximum none). Prices round up to the next $0.10.",
      ),
    ).toBeTruthy();
    const fan = within(table).getByText("Fan").closest("tr");
    expect(fan).not.toBeNull();
    if (fan === null) return;
    expect(within(fan).getByText("P0001")).toBeTruthy();
    expect(within(fan).getByText("$10.00")).toBeTruthy();
    expect(within(fan).getByText("20%")).toBeTruthy();
    expect(within(fan).getByText("$12.00")).toBeTruthy();
    const kettle = within(table).getByText("Kettle").closest("tr");
    expect(kettle?.textContent).toContain("Low stock");
    const old = within(table).getByText("Old lamp").closest("tr");
    expect(old?.textContent).toContain("Discontinued");
    expect(old?.textContent).not.toContain("Low stock");
    const service = within(table).getByText("Room cleaning").closest("tr");
    expect(service?.textContent).toContain("Service");
    // Staff see the products and their prices, but add and change nothing.
    await openEdit(table, "Fan");
    expect(
      within(table).queryByRole("button", { name: "Add product" }),
    ).toBeNull();
    expect(
      within(table).queryByRole("button", { name: "Details: Fan" }),
    ).toBeNull();
    expect(
      within(table).queryByRole("button", { name: "Mark-up: Fan" }),
    ).toBeNull();
    fireEvent.click(within(table).getByRole("button", { name: "Prices: Fan" }));
    const history = await screen.findByRole("dialog", {
      name: "Prices of Fan",
    });
    expect(await within(history).findByText("Purchase")).toBeTruthy();
    expect(within(history).getByText("Vanna")).toBeTruthy();
    expect(api.prices).toHaveBeenCalledWith("property-1", "p-fan");
    cleanup();

    show("products", apiOf(), MANAGER);
    const managed = await screen.findByRole("region", { name: "Products" });
    await openEdit(managed, "Fan");
    expect(
      within(managed).getByRole("button", { name: "Add product" }),
    ).toBeTruthy();
    expect(
      within(managed).getByRole("button", { name: "Details: Fan" }),
    ).toBeTruthy();
    expect(
      within(managed).queryByRole("button", { name: "Mark-up: Fan" }),
    ).toBeNull();
    await openEdit(managed, "Room cleaning");
    expect(
      within(managed).getByRole("button", { name: "Cost: Room cleaning" }),
    ).toBeTruthy();
    expect(
      within(managed).queryByRole("button", { name: "Cost: Fan" }),
    ).toBeNull();
    cleanup();

    show("products", apiOf(), OWNER, "km");
    const khmer = await screen.findByRole("region", { name: "ផលិតផល" });
    expect(within(khmer).getByText("កង្ហារ")).toBeTruthy();
    expect(within(khmer).getAllByText("ឧបករណ៍").length).toBeGreaterThan(0);
  });

  it("TEST-FE-1144 Add product needs a name and a Service's cost; Edit marks a product Discontinued at its version; the Owner's mark-up shows the new price and keeps it between the minimum and maximum", async () => {
    const api = apiOf();
    show("products", api, OWNER);
    const table = await screen.findByRole("region", { name: "Products" });
    fireEvent.click(within(table).getByRole("button", { name: "Add product" }));
    let dialog = screen.getByRole("dialog", { name: "Add product" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Enter a name of 1 to 120 letters.",
    );
    change(/^Name in English/, "Room cleaning deep");
    change("Category", "SERVICES");
    // A Service is counted in times, hours or bags and has no reorder level.
    expect(screen.queryByLabelText("Reorder level")).toBeNull();
    const units = within(screen.getByLabelText("Unit")).getAllByRole("option");
    expect(units.map((option) => option.textContent)).toEqual([
      "Time",
      "Hour",
      "Bag",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Enter an amount above 0",
    );
    change(/^Cost of one/, "3.33");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.addProduct).toHaveBeenCalledWith("property-1", {
        name_en: "Room cleaning deep",
        name_kh: null,
        description: null,
        category_code: "SERVICES",
        measure_unit: "TIME",
        reorder_level: null,
        reorder_quantity: null,
        service_cost_usd_cents: 333,
      });
    });
    expect((await screen.findByRole("status")).textContent).toContain(
      "Room cleaning deep added.",
    );

    await openEdit(table, "Fan");
    fireEvent.click(screen.getByRole("button", { name: "Details: Fan" }));
    dialog = screen.getByRole("dialog", { name: "Edit P0001" });
    // An Item stays an Item.
    expect(
      within(screen.getByLabelText("Category"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Furniture", "Appliances"]);
    fireEvent.click(
      screen.getByRole<HTMLInputElement>("checkbox", { name: /Discontinued/ }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.changeProduct).toHaveBeenCalledWith("property-1", FAN, {
        name_en: "Fan",
        name_kh: "កង្ហារ",
        description: null,
        category_code: "APPLIANCES",
        measure_unit: "PIECE",
        reorder_level: 2,
        reorder_quantity: 5,
        discontinued: true,
      });
    });

    await openEdit(table, "Fan");
    fireEvent.click(
      await screen.findByRole("button", { name: "Mark-up: Fan" }),
    );
    dialog = screen.getByRole("dialog", { name: "Mark-up for Fan" });
    change("Mark-up (%)", "30");
    expect(within(dialog).getByText("New price $13.00")).toBeTruthy();
    change("Maximum (%)", "25");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "between the minimum and the maximum",
    );
    change("Maximum (%)", "40");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.setMarkUps).toHaveBeenCalledWith("property-1", FAN, {
        mark_up_basis_points: 3000,
        min_mark_up_basis_points: 1500,
        max_mark_up_basis_points: 4000,
      });
    });
  });

  it("TEST-FE-2211 (Property fix 9, owner 14/11/2026) a move is one row, Moved from the old place to the new one, and the details sit under the product", async () => {
    const out: Movement = {
      ...MOVEMENT,
      movement_number: "SM260005",
      kind: "TRANSFER_OUT",
      quantity: "2",
      unit_cost_usd_cents: null,
      supplier: null,
      receipt_reference: null,
    };
    const into: Movement = {
      ...out,
      kind: "TRANSFER_IN",
      quantity: "2",
      unit_id: "unit-u101",
      unit_number: "U101",
      place_item_id: BEDROOM,
      place_name_en: "Bedroom",
      place_name_kh: null,
    };
    show(
      "stock",
      apiOf({ movements: vi.fn(() => Promise.resolve([out, into, MOVEMENT])) }),
      STAFF,
    );
    const card = await screen.findByRole("region", { name: "Stock movements" });
    const rows = within(card).getAllByText("SM260005");
    expect(rows).toHaveLength(1);
    const row = rows[0]?.closest("tr");
    expect(row?.textContent).toContain("Moved");
    expect(row?.textContent).toContain("W01 · Cabinet 1 → U101 · Bedroom 1");
    // A move neither adds nor takes away, so its quantity has no sign.
    expect(row?.textContent).toContain("Vanna2 Piece");
    const purchase = within(card).getByText("SM260001").closest("tr");
    expect(purchase?.querySelector(".ui-subline")?.textContent).toContain(
      "$10.00 · Market · R-1",
    );
  });

  it("TEST-FE-1145 Stock movements: a New purchase puts an Item in a place with its cost; Move stock takes only what a place holds; Adjust stock is for a Manager or the Owner and needs a reason; a server refusal stays in the form", async () => {
    const api = apiOf({
      recordMovement: vi
        .fn()
        .mockResolvedValueOnce("SM260002")
        .mockRejectedValueOnce(
          new ProductsError(409, "There is not enough stock at this place"),
        )
        .mockResolvedValue("SM260004"),
    });
    show("stock", api, STAFF);
    const card = await screen.findByRole("region", { name: "Stock movements" });
    const row = within(card).getByText("SM260001").closest("tr");
    expect(row?.textContent).toContain("+3 Piece");
    expect(row?.textContent).toContain("W01 · Cabinet 1");
    expect(row?.textContent).toContain("$10.00 · Market · R-1");
    expect(
      within(card).queryByRole("button", { name: "Adjust stock" }),
    ).toBeNull();

    fireEvent.click(within(card).getByRole("button", { name: "New purchase" }));
    let dialog = screen.getByRole("dialog", { name: "New purchase" });
    // A discontinued product cannot be bought again; a Service has no stock.
    const choices = within(screen.getByLabelText(/^Product/))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(choices).toEqual(["Choose", "P0001 · Fan", "P0002 · Kettle"]);
    change(/^Product/, "p-fan");
    change(/^Qty/, "1.5");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "a whole number",
    );
    change(/^Qty/, "4");
    change(/^Put in/, "unit-w01|item-cabinet|2");
    change(/^Cost of one/, "8");
    expect(
      within(dialog).getByText(
        "The price is now $12.00. With this cost and a mark-up of 20%, it would be $9.60.",
      ),
    ).toBeTruthy();
    change("Supplier", "Market");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordMovement).toHaveBeenCalledWith("property-1", {
        kind: "PURCHASE",
        product_id: "p-fan",
        quantity: "4",
        from: null,
        to: { unit_id: "unit-w01", item_id: CABINET, number: 2 },
        unit_cost_usd_cents: 800,
        supplier: "Market",
        receipt_reference: null,
        reason: null,
      });
    });
    expect((await screen.findByRole("status")).textContent).toContain(
      "SM260002 saved.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Move stock" }));
    dialog = screen.getByRole("dialog", { name: "Move stock" });
    change(/^Product/, "p-fan");
    // Only the places that hold the product, with what each holds.
    expect(
      within(screen.getByLabelText(/^From/))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Choose",
      "W01 · Cabinet 1 (2 here)",
      "U101 · Bedroom 1 (1 here)",
    ]);
    change(/^Qty/, "3");
    change(/^From/, "unit-w01|item-cabinet|1");
    change(/^To/, "unit-w01|item-cabinet|1");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Choose another place",
    );
    change(/^To/, "unit-102|item-bedroom|1");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "There is only 2 at this place.",
    );
    change(/^Qty/, "2");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain(
      "Not saved: There is not enough stock at this place",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    cleanup();

    show("stock", api, MANAGER);
    fireEvent.click(
      await screen.findByRole("button", { name: "Adjust stock" }),
    );
    dialog = screen.getByRole("dialog", { name: "Adjust stock" });
    change(/^Product/, "p-old");
    change(/^Qty/, "1");
    change(/^Take from/, "unit-w01|item-cabinet|1");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Enter the reason.",
    );
    change(/^Reason/, "Broken");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordMovement).toHaveBeenLastCalledWith("property-1", {
        kind: "ADJUSTMENT_OUT",
        product_id: "p-old",
        quantity: "1",
        from: { unit_id: "unit-w01", item_id: CABINET, number: 1 },
        to: null,
        unit_cost_usd_cents: null,
        supplier: null,
        receipt_reference: null,
        reason: "Broken",
      });
    });
  });

  it("TEST-FE-1146 Locations: the warehouse shows every place with what it holds, a Unit for rent only when it holds items, and Add place gives the next number", async () => {
    const api = apiOf();
    show("locations", api, MANAGER);
    // Owner 14/11/2026: the card is named by the Unit number only, with no "Not for rent".
    const warehouse = await screen.findByRole("region", { name: "W01" });
    expect(within(warehouse).queryByText("Not for rent")).toBeNull();
    const first = within(warehouse).getByText("Cabinet 1").closest("tr");
    expect(
      [...(first?.querySelectorAll("ul.ui-holds li") ?? [])].map(
        (item) => item.textContent,
      ),
    ).toEqual(["P0001 Fan × 2", "P0003 Old lamp × 2"]);
    const second = within(warehouse).getByText("Cabinet 2").closest("tr");
    expect(second?.textContent).toContain("Empty");
    expect(screen.getByRole("region", { name: "U101" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "U102" })).toBeNull();
    fireEvent.click(
      within(warehouse).getByRole("button", { name: "Add place: W01" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Add place to Unit W01",
    });
    expect(
      within(dialog).getByText("It will be W01 · Cabinet 3."),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.addPlace).toHaveBeenCalledWith(
        "property-1",
        "unit-w01",
        CABINET,
      );
    });
    expect((await screen.findByRole("status")).textContent).toContain(
      "W01 · Cabinet 3 added.",
    );
    cleanup();
    show("locations", apiOf(), STAFF);
    await screen.findByRole("region", { name: "W01" });
    expect(screen.queryByRole("button", { name: /Add place/ })).toBeNull();
  });

  it("TEST-FE-1147 the price helpers round up to the step and quantities follow the unit", () => {
    expect(priceFor(1000, 2000, 10)).toBe(1200);
    expect(priceFor(1050, 2000, 10)).toBe(1260);
    expect(priceFor(333, 2000, 10)).toBe(400);
    expect(priceFor(800, 3000, 10)).toBe(1040);
    expect(quantityFromText("2", "PIECE")).toBe("2");
    expect(quantityFromText("2.5", "PIECE")).toBeNull();
    expect(quantityFromText("2.5", "METRE")).toBe("2.5");
    expect(quantityFromText("0", "METRE")).toBeNull();
    expect(quantityFromText("1.2345", "KILOGRAM")).toBeNull();
  });

  it('TEST-FE-1947 (owner 12/11/2026: "check all card is link to correct place") a row above the Products list shows every product or only the ones low on stock and still sold, with a count each; "?show=low" opens the list on Low stock, and the choice is kept in the address', async () => {
    const names = () =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.querySelector("b")?.textContent);
    // A product that is low but no longer sold is not counted, as on Home.
    const gone = product({
      product_id: "p-gone",
      sku: "P0005",
      name_en: "Gone bulb",
      name_kh: null,
      low_stock: true,
      discontinued: true,
    });
    const catalogue = { ...CATALOGUE, products: [...CATALOGUE.products, gone] };
    window.history.replaceState(null, "", "#/products?show=low");
    show(
      "products",
      apiOf({ catalogue: vi.fn(() => Promise.resolve(catalogue)) }),
      STAFF,
    );
    const table = await screen.findByRole("region", { name: "Products" });
    const low = await within(table).findByRole("button", {
      name: "Low stock 1",
      pressed: true,
    });
    const all = within(table).getByRole("button", { name: "All 5" });
    expect(names()).toEqual(["Kettle"]);

    fireEvent.click(all);
    expect(all.getAttribute("aria-pressed")).toBe("true");
    expect(names()).toHaveLength(5);
    expect(window.location.hash).toBe("#/products");
    fireEvent.click(low);
    expect(names()).toEqual(["Kettle"]);
    expect(window.location.hash).toBe("#/products?show=low");
    cleanup();

    // Nothing low: the list says so; with no product at all there is no row to choose from.
    const fine = { ...CATALOGUE, products: [FAN] };
    show(
      "products",
      apiOf({ catalogue: vi.fn(() => Promise.resolve(fine)) }),
      STAFF,
    );
    expect(await screen.findByText("No product is low on stock.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Low stock 0" })).toBeTruthy();
    cleanup();
    window.history.replaceState(null, "", "#/products");
    show(
      "products",
      apiOf({
        catalogue: vi.fn(() => Promise.resolve({ ...CATALOGUE, products: [] })),
      }),
      STAFF,
    );
    await screen.findByRole("region", { name: "Products" });
    expect(screen.queryByRole("button", { name: /^Low stock/ })).toBeNull();
  });
});
