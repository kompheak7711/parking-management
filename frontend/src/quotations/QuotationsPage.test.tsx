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
import type {
  Catalogue,
  Locations,
  Product,
  ProductsApi,
} from "../products/productsClient";
import { QuotationsPage } from "./QuotationsPage";
import {
  type Quotation,
  type QuotationLine,
  QuotationsError,
  type QuotationsApi,
} from "./quotationsClient";

const TODAY = "2026-11-04";

beforeEach(() => {
  window.location.hash = "#/quotations";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
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
    stock: "2",
    low_stock: false,
    ...extra,
  };
}

const FAN = product({});
const CLEANING = product({
  product_id: "p-clean",
  sku: "P0002",
  name_en: "Extra cleaning",
  name_kh: null,
  category_code: "SERVICES",
  kind: "SERVICE",
  measure_unit: "TIME",
  price_usd_cents: 1500,
  stock: "0",
});
const KETTLE = product({
  product_id: "p-kettle",
  sku: "P0003",
  name_en: "Kettle",
  name_kh: null,
  price_usd_cents: null,
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
    { code: "APPLIANCES", name_en: "Appliances", name_kh: null, kind: "ITEM" },
    { code: "SERVICES", name_en: "Services", name_kh: null, kind: "SERVICE" },
  ],
  products: [FAN, CLEANING, KETTLE],
};

const LOCATIONS: Locations = {
  places: [
    {
      unit_id: "unit-w01",
      unit_number: "W01",
      for_rent: false,
      item_id: "item-cabinet",
      name_en: "Cabinet",
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
      unit_id: "unit-w01",
      unit_number: "W01",
      for_rent: false,
      item_id: "item-cabinet",
      name_en: "Cabinet",
      name_kh: null,
      number: 2,
      stock: [
        {
          product_id: "p-fan",
          sku: "P0001",
          name_en: "Fan",
          measure_unit: "PIECE",
          quantity: "3",
        },
      ],
    },
  ],
  features: [],
};

function line(extra: Partial<QuotationLine>): QuotationLine {
  return {
    position: 1,
    product_id: "p-fan",
    sku: "P0001",
    name_en: "Fan",
    name_kh: "កង្ហារ",
    kind: "ITEM",
    measure_unit: "PIECE",
    quantity: 2,
    list_price_usd_cents: 3000,
    price_usd_cents: 3000,
    amount_usd_cents: 6000,
    taken_from: null,
    ...extra,
  };
}

function quotation(extra: Partial<Quotation>): Quotation {
  return {
    quotation_id: "q-1",
    quotation_number: "QT260001",
    status: "WAITING",
    state: "WAITING",
    customer_id: "cust-sok",
    customer_name: "Sok Dara",
    customer_phone: "012 345 678",
    lease_id: "lease-101",
    unit_number: "U101",
    note: "Fan for the bedroom",
    made_on: "2026-11-02",
    valid_until: "2026-11-09",
    due_days: 7,
    total_usd_cents: 7500,
    lowered_reason: null,
    replaces_id: null,
    replaces_number: null,
    replaced_by_id: null,
    replaced_by_number: null,
    signed_on: null,
    signed_at: null,
    signed_by_name: null,
    invoice_id: null,
    invoice_number: null,
    invoice_status: null,
    refused_reason: null,
    closed_at: null,
    closed_by_name: null,
    created_at: "2026-11-02T03:05:00Z",
    created_by_name: "Chan Sophea",
    version: 1,
    lines: [
      line({}),
      line({
        position: 2,
        product_id: "p-clean",
        sku: "P0002",
        name_en: "Extra cleaning",
        name_kh: null,
        kind: "SERVICE",
        measure_unit: "TIME",
        quantity: 1,
        list_price_usd_cents: 1500,
        price_usd_cents: 1500,
        amount_usd_cents: 1500,
      }),
    ],
    ...extra,
  };
}

const WAITING = quotation({});
const SIGNED = quotation({
  quotation_id: "q-2",
  quotation_number: "QT260002",
  status: "SIGNED",
  state: "SIGNED",
  customer_id: "cust-chan",
  customer_name: "Chan Vanna",
  unit_number: "U201",
  signed_on: "2026-11-03",
  signed_at: "2026-11-03T02:00:00Z",
  invoice_id: "inv-9",
  invoice_number: "INV260009",
  invoice_status: "ISSUED",
  version: 2,
});
const EXPIRED = quotation({
  quotation_id: "q-3",
  quotation_number: "QT260003",
  state: "EXPIRED",
  made_on: "2026-10-20",
  valid_until: "2026-10-27",
});
const REFUSED = quotation({
  quotation_id: "q-4",
  quotation_number: "QT260004",
  status: "REFUSED",
  state: "REFUSED",
  refused_reason: "Too dear",
  closed_at: "2026-11-03T05:00:00Z",
});

function lease(id: string, unit: string, customer: string, name: string) {
  return {
    lease_id: id,
    unit_number: unit,
    primary_tenant_id: customer,
    primary_tenant_name: name,
    status: "SIGNED",
    start_date: "2026-03-01",
  } as LeaseResource;
}

function leaseApi(): Pick<LeaseApi, "list"> {
  return {
    list: vi.fn().mockResolvedValue({
      items: [
        lease("lease-101", "U101", "cust-sok", "Sok Dara"),
        lease("lease-201", "U201", "cust-chan", "Chan Vanna"),
      ],
      next_cursor: null,
      can_create: false,
    }),
  };
}

function apiOf(extra: Partial<QuotationsApi> = {}): QuotationsApi {
  const all = [WAITING, SIGNED, EXPIRED, REFUSED];
  return {
    list: vi.fn().mockResolvedValue(all),
    get: vi.fn((_: string, id: string) => {
      const found = all.find((item) => item.quotation_id === id);
      return found === undefined
        ? Promise.reject(new QuotationsError(404))
        : Promise.resolve(found);
    }),
    make: vi.fn(),
    sign: vi.fn(),
    refuse: vi.fn(),
    ...extra,
  };
}

function productsOf(): Pick<ProductsApi, "catalogue" | "locations"> {
  return {
    catalogue: vi.fn().mockResolvedValue(CATALOGUE),
    locations: vi.fn().mockResolvedValue(LOCATIONS),
  };
}

const STAFF = new Set(["quotations.read"]);
const MAKER = new Set(["quotations.read", "quotations.make"]);
const MANAGER = new Set([
  "quotations.read",
  "quotations.make",
  "quotations.lower_price",
]);

function show(
  api: QuotationsApi,
  capabilities: ReadonlySet<string>,
  products = productsOf(),
) {
  render(
    <QuotationsPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      leaseApi={leaseApi()}
      productsApi={products}
      propertyId="property-1"
      today={TODAY}
    />,
  );
  return products;
}

describe("Office › Invoices › Quotations (V1.1 part 6, DL-123)", () => {
  it("TEST-FE-1152 The list shows the cards, each Quotation with its Customer, days, amount and status, filters by card, and shows New Quotation only to a person who may make one", async () => {
    show(apiOf(), STAFF);
    expect(await screen.findByText("QT260001")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "New Quotation" })).toBeNull();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByText("INV260009")).toBeTruthy();
    expect(within(table).getAllByText("Expired")).toHaveLength(1);
    expect(within(table).getAllByText("Customer declined")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: /^Waiting for signature: 1\./ }),
    );
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(
      2,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /^Expired or declined: 2\./ }),
    );
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(
      3,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(
      5,
    );
    expect(screen.getByText("4 Quotations")).toBeTruthy();
    cleanup();

    show(apiOf(), MAKER);
    expect(
      (await screen.findByRole("link", { name: "New Quotation" })).getAttribute(
        "href",
      ),
    ).toBe("#/quotations/new");
  });

  it("TEST-FE-1153 New Quotation picks a Customer with a signed Lease and products with the price from Products, adds a row when the last is used, keeps the price locked without the right, checks the form and saves the lines", async () => {
    window.location.hash = "#/quotations/new";
    const made = quotation({
      quotation_id: "q-9",
      quotation_number: "QT260009",
    });
    const make = vi.fn().mockResolvedValue(made);
    show(apiOf({ make, get: vi.fn().mockResolvedValue(made) }), MAKER);
    expect(
      await screen.findByRole("heading", { name: "New Quotation" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Save and print Quotation" }),
    );
    expect(await screen.findByText("Fix 2 things:")).toBeTruthy();
    expect(make).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/^Customer/), {
      target: { value: "cust-chan" },
    });
    const first = screen.getByLabelText("Product, 1");
    // A product with no price yet cannot be picked.
    expect(
      within(first).getByRole("option", { name: /Kettle/ }),
    ).toHaveProperty("disabled", true);
    expect(
      within(first).getByRole("option", { name: "Fan · $30.00 · 2 in stock" }),
    ).toBeTruthy();
    fireEvent.change(first, { target: { value: "p-fan" } });
    expect(screen.getByLabelText("Price, 1")).toHaveProperty("value", "30.00");
    expect(screen.getByLabelText("Price, 1")).toHaveProperty("readOnly", true);
    expect(
      screen.getByText(
        "Price comes from Products. Only a Manager or the Owner can lower it.",
      ),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Qty, 1"), {
      target: { value: "3" },
    });
    expect(screen.getByLabelText("Amount, 1").textContent).toBe("$90.00");
    fireEvent.change(screen.getByLabelText("Product, 2"), {
      target: { value: "p-clean" },
    });
    expect(screen.getByLabelText("Product, 3")).toBeTruthy();
    expect(screen.getByText("$105.00", { selector: "b" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Note for the Customer/), {
      target: { value: " Fan for the bedroom " },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save and print Quotation" }),
    );
    await waitFor(() => {
      expect(make).toHaveBeenCalledTimes(1);
    });
    expect(make).toHaveBeenCalledWith("property-1", {
      customer_id: "cust-chan",
      lease_id: "lease-201",
      note: "Fan for the bedroom",
      replaces_id: null,
      lowered_reason: null,
      lines: [
        { product_id: "p-fan", quantity: 3, price_usd_cents: 3000 },
        { product_id: "p-clean", quantity: 1, price_usd_cents: 1500 },
      ],
    });
    await waitFor(() => {
      expect(window.location.hash).toBe("#/quotations/qt%3Aq-9");
    });
    expect(
      await screen.findByText(
        "Quotation QT260009 saved. Print it for the Customer to sign.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-1154 Lower the price makes a new version for the same Customer: a price above the list is refused, a lower price shows the list price and needs its reason, and the new Quotation replaces the waiting one", async () => {
    show(apiOf(), MAKER);
    window.location.hash = "#/quotations/qt:q-1";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "QT260001" }),
    ).toBeTruthy();
    // Without "Lower a price on a Quotation" there is no Lower the price.
    expect(
      screen.queryByRole("link", { name: "Lower the price (new version)" }),
    ).toBeNull();
    cleanup();

    const make = vi.fn().mockResolvedValue(quotation({ quotation_id: "q-10" }));
    window.location.hash = "#/quotations/qt:q-1";
    show(apiOf({ make }), MANAGER);
    const lower = await screen.findByRole("link", {
      name: "Lower the price (new version)",
    });
    expect(lower.getAttribute("href")).toBe("#/quotations/new%3Aq-1");
    window.location.hash = "#/quotations/new:q-1";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "New version of QT260001" }),
    ).toBeTruthy();
    expect(screen.getByLabelText(/^Customer/)).toHaveProperty("disabled", true);
    const price = screen.getByLabelText("Price, 2");
    expect(price).toHaveProperty("readOnly", false);
    fireEvent.change(price, { target: { value: "16.00" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Save and print Quotation" }),
    );
    expect(
      await screen.findAllByText("A price cannot be above the list price."),
    ).toHaveLength(2);
    fireEvent.change(price, { target: { value: "12.00" } });
    expect(screen.getByText("List price $15.00")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Save and print Quotation" }),
    );
    expect(
      await screen.findAllByText("Enter why the price is lower."),
    ).toHaveLength(2);
    fireEvent.change(screen.getByLabelText(/^Why the price is lower/), {
      target: { value: "Long-time tenant" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save and print Quotation" }),
    );
    await waitFor(() => {
      expect(make).toHaveBeenCalledTimes(1);
    });
    expect(make.mock.calls[0]?.[1]).toMatchObject({
      customer_id: "cust-sok",
      replaces_id: "q-1",
      lowered_reason: "Long-time tenant",
      lines: [
        { product_id: "p-fan", quantity: 2, price_usd_cents: 3000 },
        { product_id: "p-clean", quantity: 1, price_usd_cents: 1200 },
      ],
    });
  });

  it("TEST-FE-1155 Customer signed asks for the day and where each Item is taken from, refuses a place without enough stock, issues the Invoice and then links to it; a 409 says the Quotation waits for stock", async () => {
    const signed = {
      ...SIGNED,
      quotation_id: "q-1",
      quotation_number: "QT260001",
    };
    const sign = vi
      .fn()
      .mockRejectedValueOnce(new QuotationsError(409))
      .mockResolvedValue(signed);
    window.location.hash = "#/quotations/qt:q-1";
    show(apiOf({ sign }), MAKER);
    fireEvent.click(
      await screen.findByRole("button", { name: "Customer signed" }),
    );
    const dialog = await screen.findByRole("dialog");
    const take = await within(dialog).findByLabelText("Take from: Fan × 2");
    // The first place that holds enough is chosen; a place with too few can still be picked.
    expect(take).toHaveProperty("value", "unit-w01|item-cabinet|2");
    fireEvent.change(take, { target: { value: "unit-w01|item-cabinet|1" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    expect(
      await within(dialog).findByText(
        "Only 1 at W01 · Cabinet 1. The Quotation waits until the items are in stock.",
      ),
    ).toBeTruthy();
    expect(sign).not.toHaveBeenCalled();
    fireEvent.change(take, { target: { value: "unit-w01|item-cabinet|2" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    expect(
      await within(dialog).findByText(
        "An item is not in stock at that place. The Quotation waits; choose another place or buy the item first.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    await waitFor(() => {
      expect(sign).toHaveBeenCalledTimes(2);
    });
    expect(sign.mock.calls[1]?.slice(2)).toEqual([
      TODAY,
      [
        {
          position: 1,
          unit_id: "unit-w01",
          item_id: "item-cabinet",
          number: 2,
        },
      ],
    ]);
    expect(
      await screen.findByText(
        "Invoice INV260009 issued. Print it for the Customer.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open Invoice INV260009" })
        .getAttribute("href"),
    ).toBe("#/invoices/inv%3Ainv-9");
  });

  it("TEST-FE-1156 The printed Quotation shows the list price under a lowered line and the due days; Customer declined needs what the Customer said; an expired Quotation offers Make a new Quotation", async () => {
    const lowered = quotation({
      lowered_reason: "Long-time tenant",
      replaces_number: "QT260000",
      lines: [line({ price_usd_cents: 2500, amount_usd_cents: 5000 })],
      total_usd_cents: 5000,
    });
    const refuse = vi.fn().mockResolvedValue(REFUSED);
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    window.location.hash = "#/quotations/qt:q-1";
    show(apiOf({ get: vi.fn().mockResolvedValue(lowered), refuse }), MAKER);
    expect(await screen.findByText("List price $30.00")).toBeTruthy();
    expect(
      screen.getByText(
        /When the Customer signs, the Invoice is issued, due in 7 days\./,
      ),
    ).toBeTruthy();
    expect(screen.getByText("This Quotation replaces QT260000.")).toBeTruthy();
    expect(screen.getByText(/Lower price: Long-time tenant/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Print Quotation" }));
    expect(print).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Customer declined" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Customer declined" }),
    );
    expect(
      await within(dialog).findByText("Enter what the Customer said."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^What the Customer said/), {
      target: { value: " Too dear " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Customer declined" }),
    );
    await waitFor(() => {
      expect(refuse).toHaveBeenCalledWith("property-1", lowered, "Too dear");
    });
    expect(
      await screen.findByText("The Customer declined: Too dear"),
    ).toBeTruthy();
    print.mockRestore();
    cleanup();

    window.location.hash = "#/quotations/qt:q-3";
    show(apiOf(), MAKER);
    expect(
      await screen.findByText(
        "This Quotation expired on 27/10/2026. Make a new Quotation if the Customer still wants it.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Make a new Quotation" })
        .getAttribute("href"),
    ).toBe("#/quotations/new%3Aq-3");
    expect(
      screen.queryByRole("button", { name: "Customer signed" }),
    ).toBeNull();
  });
});
