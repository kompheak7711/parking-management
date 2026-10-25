import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomerApi } from "../customerClient";
import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceCategory,
  type InvoiceResource,
  type InvoiceStatus,
} from "../invoiceClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import { InvoicesPage } from "./InvoicesPage";
import { periodMonth } from "./invoicesData";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/invoices";
});

const TODAY = "2026-10-25";

const usd = (cents: number) => ({
  currency: "USD" as const,
  minor_units: cents,
});

function invoice(
  id: string,
  number: string,
  fields: {
    customer: string;
    lease: string | null;
    category?: InvoiceCategory;
    status?: InvoiceStatus;
    issued?: string;
    due?: string | null;
    total: number;
    paid?: number;
    adjusted?: number;
  },
): InvoiceResource {
  const status = fields.status ?? "UNPAID";
  const adjusted = fields.adjusted ?? fields.total;
  const paid = fields.paid ?? 0;
  const owed = status === "DRAFT" || status === "VOID" ? 0 : adjusted - paid;
  return {
    id,
    property_id: "property-1",
    customer_id: fields.customer,
    lease_id: fields.lease,
    invoice_number: number,
    category: fields.category ?? "RENT",
    status,
    invoice_date: fields.issued ?? "2026-09-25",
    due_date: fields.due === undefined ? "2026-10-05" : fields.due,
    billing_period: null,
    version: 1,
    original_total: usd(fields.total),
    adjusted_total: usd(adjusted),
    active_application_total: usd(paid),
    outstanding_balance: usd(owed),
    lines: [
      {
        id: `${id}-line`,
        sequence: 1,
        description:
          fields.category === "UTILITIES" ? "Electricity" : "Rent, October",
        category: fields.category ?? "RENT",
        original_amount: usd(fields.total),
        adjusted_amount: usd(adjusted),
        outstanding_balance: usd(owed),
        source: {},
        calculation_evidence: {},
        period: { start: "2026-10-01", end: "2026-10-31" },
      },
    ],
    adjustments:
      adjusted === fields.total
        ? []
        : [
            {
              reason: "Typed the wrong amount",
              occurred_at: "2026-09-26T03:00:00Z",
            },
          ],
    void_event:
      status === "VOID"
        ? { reason: "Billed twice", occurred_at: "2026-09-27T04:00:00Z" }
        : null,
    evidence: { issued_at: "2026-09-25T00:00:00Z" },
  };
}

function invoices(): InvoiceResource[] {
  return [
    invoice("inv-r1", "INV260001", {
      customer: "cust-sok",
      lease: "lease-101",
      total: 45000,
    }),
    invoice("inv-r2", "INV260002", {
      customer: "cust-chan",
      lease: "lease-201",
      status: "PARTIALLY_PAID",
      issued: "2026-10-25",
      due: "2026-11-05",
      total: 45000,
      paid: 20000,
    }),
    invoice("inv-u1", "INV260003", {
      customer: "cust-sok",
      lease: "lease-101",
      category: "UTILITIES",
      status: "PAID",
      issued: "2026-10-25",
      due: "2026-11-05",
      total: 3000,
      paid: 3000,
    }),
    invoice("inv-d1", "INV260004", {
      customer: "cust-sok",
      lease: null,
      category: "MISCELLANEOUS_CHARGES",
      status: "DRAFT",
      due: null,
      total: 1500,
    }),
    invoice("inv-v1", "INV260005", {
      customer: "cust-chan",
      lease: "lease-201",
      status: "VOID",
      total: 10000,
    }),
  ];
}

type PageApi = Pick<
  InvoiceApi,
  "list" | "get" | "issue" | "recordOneTimeCharge" | "create"
>;

function invoiceApi(list = invoices()): PageApi {
  return {
    issue: vi.fn(),
    recordOneTimeCharge: vi.fn(),
    create: vi.fn(),
    list: vi.fn().mockResolvedValue({
      items: list,
      next_cursor: null,
      capabilities: ["invoices.read"],
    }),
    get: vi.fn((id: string) => {
      const found = list.find((item) => item.id === id);
      return found === undefined
        ? Promise.reject(new InvoiceClientError(404, "NOT_FOUND", false))
        : Promise.resolve(found);
    }),
  };
}

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
    }),
  };
}

function customerApi(): Pick<CustomerApi, "list"> {
  return {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          customer_id: "cust-sok",
          legal_name: "Sok Dara",
          phone_number: "012 345 678",
          active: true,
          relationship_indicators: [],
        },
        {
          customer_id: "cust-chan",
          legal_name: "Chan Vanna",
          active: true,
          relationship_indicators: [],
        },
      ],
      next_cursor: null,
      can_manage: false,
    }),
  };
}

function show(
  options: {
    invoices?: PageApi;
    leases?: Pick<LeaseApi, "list">;
    customers?: Pick<CustomerApi, "list">;
    capabilities?: ReadonlySet<string> | null;
  } = {},
) {
  const api = options.invoices ?? invoiceApi();
  render(
    <InvoicesPage
      active
      capabilities={options.capabilities ?? null}
      customerApi={options.customers ?? customerApi()}
      invoiceApi={api}
      language="en"
      leaseApi={options.leases ?? leaseApi()}
      propertyId="property-1"
      today={TODAY}
    />,
  );
  return api;
}

function rows(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => {
      // The phone line repeats the type, Due Date and amount; it is hidden on a wide screen.
      const copy = row.cloneNode(true) as HTMLElement;
      copy.querySelectorAll(".ui-phone").forEach((item) => {
        item.remove();
      });
      return copy.textContent;
    });
}

describe("Invoices page (V1-058 R5)", () => {
  it("TEST-FE-896 The list shows the four cards with their amounts, the add-up line and every Invoice with the Draft first, its Customer and Unit, Due Date, amount, balance and status", async () => {
    show();
    expect(await screen.findByText("All Invoices")).toBeTruthy();
    const card = (name: RegExp) => screen.getByRole("button", { name });
    expect(
      card(/^Total Invoice amount: \$930\.00\. Issued Invoices\n3 Invoices$/),
    ).toBeTruthy();
    expect(card(/^Total unpaid: \$700\.00\./)).toBeTruthy();
    expect(card(/^Total overdue: \$450\.00\./)).toBeTruthy();
    expect(card(/^Total paid: \$230\.00\./)).toBeTruthy();
    expect(
      screen.getByText(
        "Paid $230.00 + unpaid $700.00 = $930.00. Overdue $450.00 is part of unpaid. 1 Draft is not counted until it is issued.",
      ),
    ).toBeTruthy();
    expect(rows()).toEqual([
      "DraftSok DaraU101MiscellaneousSet when issued$15.00—Draft",
      "INV260003Sok DaraU101Utilities05/11/2026$30.00$0.00Paid",
      "INV260002Chan VannaU201Rent05/11/2026$450.00$250.00Part paid",
      "INV260005Chan VannaU201Rent05/10/2026$100.00—Void",
      "INV260001Sok DaraU101Rent05/10/2026$450.00$450.00Overdue",
    ]);
    expect(screen.getByText("3 Invoices · 1 void, not counted")).toBeTruthy();
  });

  it("TEST-FE-897 A card filters the list until Show all; This month and Pick a month show the Invoices due in that month; the Type select keeps one type", async () => {
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: /^Total overdue/ }),
    );
    expect(rows()).toEqual([
      "INV260001Sok DaraU101Rent05/10/2026$450.00$450.00Overdue",
    ]);
    expect(screen.getByText("Showing: Total overdue.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(rows()).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(screen.getByText("Invoices due in October 2026")).toBeTruthy();
    // Drafts have no Due Date, so a month leaves them out.
    expect(rows().map((row) => row.slice(0, 9))).toEqual([
      "INV260005",
      "INV260001",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Pick a month" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Month" }), {
      target: { value: "2026-11" },
    });
    expect(rows().map((row) => row.slice(0, 9))).toEqual([
      "INV260003",
      "INV260002",
    ]);
    fireEvent.change(screen.getByLabelText("Type"), {
      target: { value: "UTILITIES" },
    });
    expect(rows().map((row) => row.slice(0, 9))).toEqual(["INV260003"]);
    expect(
      screen.getByText("Paid $30.00 + unpaid $0.00 = $30.00."),
    ).toBeTruthy();
  });

  it("TEST-FE-898 An overdue Invoice page names the day it became overdue, counts the days past the Due Date, and lists what is billed, the Customer and the History", async () => {
    show();
    fireEvent.click(await screen.findByRole("link", { name: "INV260001" }));
    expect(
      await screen.findByRole("heading", { name: "INV260001" }),
    ).toBeTruthy();
    expect(window.location.hash).toBe("#/invoices/inv%3Ainv-r1");
    expect(screen.getByText("Rent · Sok Dara · U101")).toBeTruthy();
    expect(
      screen.getByText(
        "This Invoice is overdue. It became overdue on 06/10/2026, the day after its Due Date.",
      ),
    ).toBeTruthy();
    const status = screen
      .getByRole("heading", { name: "Invoice status" })
      .closest("section");
    if (status === null) throw new Error("No status card");
    expect(within(status).getByText("Days past the Due Date")).toBeTruthy();
    expect(within(status).getByText("20")).toBeTruthy();
    expect(within(status).getByText("Today (day +20)")).toBeTruthy();
    expect(within(status).getByText("Overdue now")).toBeTruthy();
    expect(within(status).getByText("$0.00 (0%)")).toBeTruthy();
    // The printed Invoice shows at once, Khmer above English, with the QR code while owed.
    const sheet = document.querySelector("article.doc");
    if (!(sheet instanceof HTMLElement)) throw new Error("No printed Invoice");
    expect(within(sheet).getByText("Rent, October")).toBeTruthy();
    expect(within(sheet).getByText("ថ្លៃឈ្នួល")).toBeTruthy();
    expect(within(sheet).getByText("01/10/2026 - 31/10/2026")).toBeTruthy();
    expect(within(sheet).getByText("Phone 012 345 678")).toBeTruthy();
    expect(within(sheet).getByText("Unit U101")).toBeTruthy();
    expect(sheet.querySelector(".due .n")?.textContent).toBe("$450.00");
    expect(
      within(sheet).getByRole("img", {
        name: "ABA KHQR code for CHETANA APARTMENT",
      }),
    ).toBeTruthy();
    expect(
      within(sheet).getByText(/a late-payment charge of 10%/),
    ).toBeTruthy();
    expect(screen.getByText("Became overdue with $450.00 unpaid")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Customer" }).getAttribute("href"),
    ).toBe("#/customers/cust-sok");
    expect(
      screen.getByRole("link", { name: "Open Lease" }).getAttribute("href"),
    ).toBe("#/leases/lease-101");

    fireEvent.click(
      screen.getByRole("link", { name: "All Invoices for U101" }),
    );
    await waitFor(() => {
      expect(screen.getByText("Showing only Sok Dara")).toBeTruthy();
    });
    expect(rows().map((row) => row.slice(0, 9))).toEqual([
      "DraftSok ",
      "INV260003",
      "INV260001",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Show everyone" }));
    await waitFor(() => {
      expect(rows()).toHaveLength(5);
    });
  });

  it("TEST-FE-899 A part-paid Invoice counts the days until its Due Date; a Draft, a void and an adjusted Invoice say so; a missing Invoice is named", async () => {
    const list = invoices();
    list.push(
      invoice("inv-a1", "INV260006", {
        customer: "cust-chan",
        lease: "lease-201",
        issued: "2026-10-25",
        due: "2026-11-05",
        total: 45000,
        adjusted: 40000,
      }),
    );
    window.location.hash = "#/invoices/inv:inv-r2";
    show({ invoices: invoiceApi(list) });
    expect(await screen.findByText("Days until the Due Date")).toBeTruthy();
    expect(screen.getByText("11")).toBeTruthy();
    expect(screen.getByText("$200.00 (44%)")).toBeTruthy();
    const card = screen
      .getByRole("heading", { name: "Invoice status" })
      .closest("section");
    if (card === null) throw new Error("No status card");
    expect(within(card).getByText("Balance due")).toBeTruthy();
    // The printed Invoice takes off what is paid.
    expect(screen.getByText("− $200.00")).toBeTruthy();
    cleanup();

    window.location.hash = "#/invoices/inv:inv-d1";
    show({ invoices: invoiceApi(list) });
    expect(
      await screen.findByText(
        "This is a Draft. It has no Due Date and is not owed until it is issued.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Draft" })).toBeTruthy();
    cleanup();

    window.location.hash = "#/invoices/inv:inv-v1";
    show({ invoices: invoiceApi(list) });
    expect(
      await screen.findByText(
        "This Invoice is void. Nobody owes it. It stays here with its history.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Voided: Billed twice")).toBeTruthy();
    cleanup();

    window.location.hash = "#/invoices/inv:inv-a1";
    show({ invoices: invoiceApi(list) });
    expect(await screen.findByText("Total after adjustments")).toBeTruthy();
    expect(screen.getByText("Was $450.00")).toBeTruthy();
    expect(screen.getByText("Adjusted: Typed the wrong amount")).toBeTruthy();
    cleanup();

    window.location.hash = "#/invoices/inv:nothing";
    show({ invoices: invoiceApi(list) });
    expect(
      await screen.findByText(
        "This Invoice was not found, or you may not see it.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-900 A person who may not read Customers or Leases still sees the Invoices without names; a failed Invoice list offers Retry", async () => {
    const refused = { list: vi.fn().mockRejectedValue(new Error("403")) };
    show({
      customers: refused,
      leases: refused,
      capabilities: new Set(["invoices.read"]),
    });
    expect(await screen.findByText("All Invoices")).toBeTruthy();
    expect(screen.getAllByText("Customer not shown")).toHaveLength(5);
    cleanup();

    const list = vi
      .fn()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", false))
      .mockResolvedValue({
        items: invoices(),
        next_cursor: null,
        capabilities: [],
      });
    show({ invoices: { ...invoiceApi(), list } });
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("All Invoices")).toBeTruthy();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("TEST-FE-901 An overpaid Invoice still adds up, an Invoice due today is not overdue, the list reads every page, a month still names the Drafts left out, and voids are not counted", async () => {
    const first = [
      invoice("inv-x1", "INV260010", {
        customer: "cust-sok",
        lease: "lease-101",
        status: "PAID",
        due: TODAY,
        total: 10000,
        paid: 12000,
      }),
      invoice("inv-x2", "INV260011", {
        customer: "cust-chan",
        lease: "lease-201",
        due: TODAY,
        total: 5000,
      }),
    ];
    const second = invoices();
    const list = vi
      .fn()
      .mockResolvedValueOnce({
        items: first,
        next_cursor: "page-2",
        capabilities: [],
      })
      .mockResolvedValueOnce({
        items: second,
        next_cursor: null,
        capabilities: [],
      });
    show({ invoices: { ...invoiceApi(), list } });
    expect(await screen.findByText("All Invoices")).toBeTruthy();
    expect(list).toHaveBeenLastCalledWith("property-1", { cursor: "page-2" });
    // Overpaid counts as its total; due today is not overdue yet.
    expect(
      screen.getByText(
        "Paid $330.00 + unpaid $750.00 = $1,080.00. Overdue $450.00 is part of unpaid. 1 Draft is not counted until it is issued.",
      ),
    ).toBeTruthy();
    expect(rows().find((row) => row.startsWith("INV260011"))).toContain(
      "Not paid",
    );
    expect(screen.getByText("5 Invoices · 1 void, not counted")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(rows().map((row) => row.slice(0, 9))).toEqual([
      "INV260011",
      "INV260010",
      "INV260005",
      "INV260001",
    ]);
    expect(
      screen.getByText(/1 Draft is not counted until it is issued\.$/),
    ).toBeTruthy();
  });

  it("TEST-FE-902 Last month in January is December; an Invoice of another Property is not shown on its page", async () => {
    expect(periodMonth("last", "2027-01-10", "")).toBe("2026-12");
    expect(periodMonth("month", "2027-01-10", "")).toBe("2027-01");
    expect(periodMonth("pick", "2027-01-10", "2026-08")).toBe("2026-08");
    expect(periodMonth("all", "2027-01-10", "")).toBeNull();
    const other = invoice("inv-o1", "INV270001", {
      customer: "cust-sok",
      lease: null,
      total: 1000,
    });
    other.property_id = "property-2";
    window.location.hash = "#/invoices/inv:inv-o1";
    show({ invoices: invoiceApi([other]) });
    expect(
      await screen.findByText(
        "This Invoice was not found, or you may not see it.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-903 Print Invoice prints only the sheet; a Utility line shows its use and rate; a Draft or void sheet is stamped and a paid, Draft or void one has no QR code", async () => {
    const list = invoices();
    const utility = list[2];
    if (utility === undefined) throw new Error("No Utility Invoice");
    const line = utility.lines[0];
    if (line === undefined) throw new Error("No line");
    line.calculation_evidence = {
      utility_type: "ELECTRICITY",
      consumption_quantity: "1240",
      rate_usd_per_unit: "0.25",
    };
    const print = vi.spyOn(window, "print").mockImplementation(() => {
      expect(document.body.classList.contains("ui-printing")).toBe(true);
    });
    window.location.hash = "#/invoices/inv:inv-r1";
    show({ invoices: invoiceApi(list) });
    fireEvent.click(
      await screen.findByRole("button", { name: "Print Invoice" }),
    );
    expect(print).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("afterprint"));
    expect(document.body.classList.contains("ui-printing")).toBe(false);
    print.mockRestore();
    cleanup();

    const sheetOf = async (id: string) => {
      window.location.hash = `#/invoices/inv:${id}`;
      show({ invoices: invoiceApi(list) });
      await screen.findByRole("button", { name: "Print Invoice" });
      const sheet = document.querySelector("article.doc");
      if (!(sheet instanceof HTMLElement)) throw new Error("No sheet");
      return sheet;
    };
    let sheet = await sheetOf("inv-u1");
    expect(within(sheet).getByText("ថ្លៃភ្លើង")).toBeTruthy();
    expect(within(sheet).getByText("1,240 kWh × $0.25")).toBeTruthy();
    expect(within(sheet).queryByRole("img", { name: /KHQR/ })).toBeNull();
    expect(within(sheet).queryByText(/late-payment charge/)).toBeNull();
    cleanup();

    sheet = await sheetOf("inv-d1");
    expect(within(sheet).getByText("DRAFT · សេចក្តីព្រាង")).toBeTruthy();
    expect(within(sheet).queryByText("INV260004")).toBeNull();
    expect(within(sheet).queryByRole("img", { name: /KHQR/ })).toBeNull();
    cleanup();

    sheet = await sheetOf("inv-v1");
    expect(within(sheet).getByText("VOID · ទុកជាមោឃៈ")).toBeTruthy();
    expect(sheet.querySelector(".due .n")?.textContent).toBe("$0.00");
    expect(within(sheet).queryByRole("img", { name: /KHQR/ })).toBeNull();
  });

  it("TEST-FE-904 Create Invoice checks every box, confirms, records the charge and makes a Draft once even when pressed again after no answer; Damage points to Move-out; it needs invoices.create", async () => {
    const api = invoiceApi();
    const draft = invoice("inv-new", "INV260099", {
      customer: "cust-chan",
      lease: "lease-201",
      category: "MISCELLANEOUS_CHARGES",
      status: "DRAFT",
      due: null,
      total: 1250,
    });
    const record = vi
      .fn()
      .mockRejectedValueOnce(new InvoiceClientError(null, "NETWORK", true))
      .mockImplementation((_property: string, input: { charge_id: string }) =>
        Promise.resolve({ obligation_id: input.charge_id }),
      );
    const create = vi.fn().mockResolvedValue(draft);
    api.recordOneTimeCharge = record;
    api.create = create;
    show({ invoices: api, capabilities: new Set(["invoices.create"]) });
    fireEvent.click(
      await screen.findByRole("link", { name: "Create Invoice" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Create Invoice" }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Damage" }));
    expect(
      screen.getByText(
        "A Damage charge comes from a finding in a Move-out inspection, and is entered there.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Miscellaneous" }));

    fireEvent.change(screen.getByLabelText(/^Amount/), {
      target: { value: "12.505" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Draft Invoice" }));
    expect(
      await screen.findByText("Fix 5 thing(s) before saving."),
    ).toBeTruthy();
    expect(
      screen.getAllByText(
        "Enter the amount in dollars and cents, for example 353.00.",
      ),
    ).toHaveLength(2);

    const customer = screen.getByLabelText(/^Customer/);
    expect(
      within(customer)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a Customer", "Sok Dara · U101", "Chan Vanna · U201"]);
    fireEvent.change(customer, { target: { value: "cust-chan" } });
    fireEvent.change(screen.getByLabelText(/^What is charged/), {
      target: { value: " Replacement key card " },
    });
    fireEvent.change(screen.getByLabelText(/^Amount/), {
      target: { value: "12.5" },
    });
    fireEvent.change(screen.getByLabelText(/^Reason/), {
      target: { value: "Lost key card" },
    });
    fireEvent.change(screen.getByLabelText(/^What approves it/), {
      target: { value: "Signed key-card form" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Draft Invoice" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Save this Draft Invoice?",
    });
    expect(within(dialog).getByText("Chan Vanna · U201")).toBeTruthy();
    expect(within(dialog).getByText("$12.50")).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Draft Invoice" }),
    );
    expect(
      await within(dialog).findByText(
        "We could not tell if this was saved. Press the button again: it is saved only once.",
      ),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save Draft Invoice" }),
    );
    expect(await screen.findByText("Draft Invoice saved")).toBeTruthy();
    expect(record).toHaveBeenCalledTimes(2);
    const [first, second] = record.mock.calls as [
      string,
      Record<string, unknown>,
      string,
    ][];
    expect(second).toEqual(first);
    expect(first?.[1]).toMatchObject({
      category: "MISCELLANEOUS_CHARGES",
      customer_id: "cust-chan",
      lease_id: "lease-201",
      description: "Replacement key card",
      amount: { currency: "USD", minor_units: 1250 },
      reason: "Lost key card",
      evidence_reference: "Signed key-card form",
    });
    expect(create).toHaveBeenCalledWith(
      "property-1",
      first?.[1].charge_id,
      expect.any(String),
    );
    expect(
      screen.getByText(
        "Draft for Chan Vanna, U201: Replacement key card, $12.50. A Manager checks it and issues it.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Draft" }).getAttribute("href"),
    ).toBe("#/invoices/inv%3Ainv-new");
    cleanup();

    window.location.hash = "#/invoices";
    show({ capabilities: new Set(["invoices.read"]) });
    expect(await screen.findByText("All Invoices")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Create Invoice" })).toBeNull();
  });

  it("TEST-FE-905 Issue Invoice gives a Draft its number with the Settings Due Date, or another date with a reason; a change meanwhile reads the Invoice again; it needs invoices.issue", async () => {
    const list = invoices();
    const draft = list[3];
    if (draft === undefined) throw new Error("No Draft");
    const issued: InvoiceResource = {
      ...draft,
      status: "UNPAID",
      invoice_number: "INV260004",
      invoice_date: TODAY,
      due_date: "2026-11-01",
      outstanding_balance: draft.adjusted_total,
      version: 2,
    };
    const api = invoiceApi(list);
    const issue = vi
      .fn()
      .mockRejectedValueOnce(new InvoiceClientError(409, "CONFLICT", false))
      .mockResolvedValue(issued);
    api.issue = issue;
    window.location.hash = "#/invoices/inv:inv-d1";
    show({ invoices: api, capabilities: new Set(["invoices.issue"]) });
    fireEvent.click(
      await screen.findByRole("button", { name: "Issue Invoice" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Issue this Invoice?" });
    expect(
      within(dialog).getByText(
        "It gets its Invoice number now, and Sok Dara owes $15.00. An issued Invoice cannot be changed, only adjusted or voided.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByLabelText("Choose another Due Date"));
    fireEvent.change(within(dialog).getByLabelText("Due Date"), {
      target: { value: "2026-10-20" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    expect(
      within(dialog).getByText("Choose a Due Date from today on."),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Write why the Invoice has this Due Date."),
    ).toBeTruthy();
    expect(issue).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Due Date"), {
      target: { value: "2026-11-01" },
    });
    fireEvent.change(within(dialog).getByLabelText("Why this date"), {
      target: { value: "Customer is paid on the 1st" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    expect(
      await screen.findByText(
        "This Invoice changed meanwhile. It is shown again as it is now; check it and try again.",
      ),
    ).toBeTruthy();
    expect(issue).toHaveBeenLastCalledWith("inv-d1", 1, expect.any(String), {
      due_date: "2026-11-01",
      due_date_reason: "Customer is paid on the 1st",
    });

    fireEvent.click(screen.getByRole("button", { name: "Issue Invoice" }));
    dialog = screen.getByRole("dialog", { name: "Issue this Invoice?" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Issue Invoice" }),
    );
    expect(
      await screen.findByText("Issued as INV260004. Due on 01/11/2026."),
    ).toBeTruthy();
    expect(issue).toHaveBeenLastCalledWith(
      "inv-d1",
      1,
      expect.any(String),
      undefined,
    );
    expect(screen.getByRole("heading", { name: "INV260004" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Issue Invoice" })).toBeNull();
    cleanup();

    show({
      invoices: invoiceApi(list),
      capabilities: new Set(["invoices.read"]),
    });
    expect(await screen.findByRole("heading", { name: "Draft" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Issue Invoice" })).toBeNull();
  });
});
