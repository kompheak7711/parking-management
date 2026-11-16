import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LedgerError } from "./ledgerClient";
import { SpendingPage, type SpendingTab } from "./SpendingPage";
import type {
  ExpenseRequest,
  ExpenseRow,
  RequestDetail,
  SpendingApi,
  SpendingForm,
  SupplierBill,
} from "./spendingClient";

function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`missing item ${String(index)}`);
  return item;
}

beforeEach(() => {
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

const ME = "actor-me";

const FORM: SpendingForm = {
  today: "2027-02-10",
  expense_limit_cents: 10_000,
  asset_limit_cents: 50_000,
  report_days: 3,
  bill_days: 30,
  rate: { id: "rate-1", khr_per_usd: 4_100 },
  accounts: [
    {
      code: "6050",
      name_en: "Repairs and maintenance",
      name_km: "ការជួសជុល និងថែទាំ",
      account_type: "EXPENSE",
    },
    {
      code: "6010",
      name_en: "Electricity bill (EDC)",
      name_km: null,
      account_type: "EXPENSE",
    },
    {
      code: "1520",
      name_en: "Furniture and appliances in Units",
      name_km: null,
      account_type: "ASSET",
    },
  ],
  money_accounts: [
    {
      code: "1010",
      name_en: "Cash on hand (USD)",
      name_km: null,
      account_type: "ASSET",
    },
    {
      code: "1020",
      name_en: "ABA Bank · USD account",
      name_km: null,
      account_type: "ASSET",
    },
    {
      code: "1030",
      name_en: "Petty cash",
      name_km: null,
      account_type: "ASSET",
    },
  ],
  suppliers: [{ id: "sup-1", name: "Sok Hardware" }],
  units: [{ id: "unit-1", unit_number: "U205" }],
};

function req(extra: Partial<ExpenseRequest>): ExpenseRequest {
  return {
    id: "r-1",
    request_number: "ER270001",
    kind: "REQUEST",
    status: "WAITING",
    requested_by: "actor-staff",
    requested_by_name: "Chan Sophea",
    account_code: "6050",
    account_name: "Repairs and maintenance",
    account_name_km: "ការជួសជុល និងថែទាំ",
    description: "Bathroom tap leaking",
    reason: "Bathroom tap leaking",
    amount_cents: 6_000,
    original_currency: "USD",
    original_amount_minor: null,
    paid_how: "ADVANCE",
    paid_from_code: null,
    paid_from_name: null,
    paid_from_name_km: null,
    supplier_name: "Sok Hardware",
    unit_number: "U205",
    spent_on: null,
    decided_at: null,
    decision_note: null,
    own_spending_note: null,
    void_reason: null,
    created_at: "2027-02-09T08:30:00+07:00",
    is_late: false,
    advance_late: false,
    owed_to_staff_cents: 0,
    ...extra,
  };
}

const REQUESTS: ExpenseRequest[] = [
  req({}),
  req({
    id: "r-2",
    request_number: "ER270002",
    amount_cents: 52_000,
    account_code: "1520",
    account_name: "Furniture and appliances in Units",
    account_name_km: null,
    description: "Fridge in U204",
    paid_how: "CASH",
    paid_from_code: "1020",
    paid_from_name: "ABA Bank · USD account",
    unit_number: null,
  }),
  req({
    id: "r-3",
    request_number: "ER270003",
    status: "PAID_OUT",
    advance_late: true,
  }),
  req({
    id: "r-4",
    request_number: "ER270004",
    kind: "URGENT_REPORT",
    status: "DONE",
    paid_how: "OWN_MONEY",
    owed_to_staff_cents: 2_500,
    amount_cents: 2_500,
    spent_on: "2027-02-01",
  }),
  req({
    id: "r-5",
    request_number: "ER270005",
    requested_by: ME,
    requested_by_name: "Me",
  }),
  req({
    id: "r-6",
    request_number: "ER270006",
    status: "VOID",
    void_reason: "Sent twice",
  }),
];

const DETAIL: RequestDetail = {
  ...req({ id: "r-3", request_number: "ER270003", status: "DONE" }),
  steps: [
    {
      step: "SUBMITTED",
      note: null,
      at: "2027-02-09T08:30:00+07:00",
      by_name: "Chan Sophea",
    },
    {
      step: "APPROVED",
      note: null,
      at: "2027-02-09T09:00:00+07:00",
      by_name: "Sok Chenda",
    },
    {
      step: "PAID_OUT",
      note: null,
      at: "2027-02-09T09:05:00+07:00",
      by_name: null,
    },
  ],
  advance: {
    amount_cents: 6_000,
    paid_on: "2027-02-09",
    entry_number: "JE270010",
    by_name: "Sok Chenda",
    from_code: "1010",
  },
  expenses: [
    {
      expense_number: "EX270004",
      expense_date: "2027-02-10",
      amount_cents: 5_000,
      bill_number: "SH-2210",
      status: "POSTED",
      entry_number: "JE270011",
      by_name: "Sok Chenda",
    },
  ],
  paybacks: [],
};

const EXPENSES: ExpenseRow[] = [
  {
    id: "x-1",
    expense_number: "EX270004",
    expense_date: "2027-02-10",
    status: "POSTED",
    account_code: "6050",
    account_name: "Repairs and maintenance",
    account_name_km: null,
    description: "Bathroom tap leaking",
    amount_cents: 5_000,
    paid_from_code: "1400",
    paid_from_name: "Staff advances",
    paid_from_name_km: null,
    bill_number: "SH-2210",
    supplier_name: "Sok Hardware",
    unit_number: "U205",
    request_number: "ER270003",
    void_reason: null,
    entry_number: "JE270011",
    supplier_bill_number: null,
    voided_by_name: null,
    voided_at: null,
    void_entry_number: null,
    bill_has_payments: false,
  },
  {
    id: "x-2",
    expense_number: "EX270003",
    expense_date: "2027-02-08",
    status: "POSTED",
    account_code: "6010",
    account_name: "Electricity bill (EDC)",
    account_name_km: null,
    description: "EDC 01/2027",
    amount_cents: 117_700,
    paid_from_code: null,
    paid_from_name: null,
    paid_from_name_km: null,
    bill_number: null,
    supplier_name: "EDC",
    unit_number: null,
    request_number: null,
    void_reason: null,
    entry_number: "JE270009",
    supplier_bill_number: "SB270001",
    voided_by_name: null,
    voided_at: null,
    void_entry_number: null,
    bill_has_payments: true,
  },
];

const BILLS: SupplierBill[] = [
  {
    id: "b-1",
    bill_number: "SB270001",
    status: "OPEN",
    supplier_name: "Lift Care Co.",
    supplier_reference: "LC-0831",
    bill_date: "2026-12-31",
    due_date: "2027-01-30",
    amount_cents: 22_000,
    still_to_pay_cents: 22_000,
    account_code: "6150",
    account_name: "Lift service",
    account_name_km: null,
    entry_number: "JE270002",
    payments: [],
  },
  {
    id: "b-2",
    bill_number: "SB270002",
    status: "OPEN",
    supplier_name: "Sok Hardware",
    supplier_reference: null,
    bill_date: "2027-02-01",
    due_date: "2027-03-03",
    amount_cents: 14_500,
    still_to_pay_cents: 4_500,
    account_code: "6050",
    account_name: "Repairs and maintenance",
    account_name_km: null,
    entry_number: "JE270005",
    payments: [
      {
        id: "p-1",
        paid_on: "2027-02-05",
        amount_cents: 10_000,
        paid_from_code: "1020",
        paid_from_name: "ABA Bank · USD account",
        paid_from_name_km: null,
        entry_number: "JE270006",
        reversed: false,
        reversal_reason: null,
        reversed_at: null,
        reversed_by_name: null,
        reversal_entry_number: null,
      },
    ],
  },
  {
    id: "b-3",
    bill_number: "SB270003",
    status: "PAID",
    supplier_name: "Kim Paint",
    supplier_reference: null,
    bill_date: "2027-01-05",
    due_date: "2027-02-04",
    amount_cents: 38_000,
    still_to_pay_cents: 0,
    account_code: "6050",
    account_name: "Repairs and maintenance",
    account_name_km: null,
    entry_number: "JE270003",
    payments: [],
  },
];

function fakeApi(extra: Partial<SpendingApi> = {}): SpendingApi {
  return {
    form: vi.fn(() => Promise.resolve(FORM)),
    requests: vi.fn(() => Promise.resolve(REQUESTS)),
    request: vi.fn(() => Promise.resolve(DETAIL)),
    expenses: vi.fn(() => Promise.resolve(EXPENSES)),
    bills: vi.fn(() => Promise.resolve(BILLS)),
    addSupplier: vi.fn(() => Promise.resolve("sup-new")),
    submitRequest: vi.fn(() => Promise.resolve("r-1")),
    decide: vi.fn(() => Promise.resolve("r-1")),
    giveAdvance: vi.fn(() => Promise.resolve("r-1")),
    recordBill: vi.fn(() => Promise.resolve("x-1")),
    payBack: vi.fn(() => Promise.resolve("pb-1")),
    voidRequest: vi.fn(() => Promise.resolve("r-1")),
    recordExpense: vi.fn(() => Promise.resolve("x-2")),
    voidExpense: vi.fn(() => Promise.resolve("x-1")),
    payBill: vi.fn(() => Promise.resolve("p-1")),
    reverseBillPayment: vi.fn(() => Promise.resolve("p-1")),
    ...extra,
  };
}

const ACCOUNTANT = new Set([
  "expenses.request",
  "expenses.approve",
  "expenses.record",
  "ledger.read",
]);
const OWNER = new Set([...ACCOUNTANT, "expenses.approve_over_limit"]);
const STAFF = new Set(["expenses.request"]);

function show(
  tab: SpendingTab,
  api: SpendingApi,
  capabilities: ReadonlySet<string> | null = ACCOUNTANT,
  language: "en" | "km" = "en",
) {
  return render(
    <SpendingPage
      active
      actorId={ME}
      api={api}
      capabilities={capabilities}
      language={language}
      propertyId="prop-1"
      tab={tab}
    />,
  );
}

async function press(name: string): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("button", { name })).toBeEnabled();
  });
  fireEvent.click(screen.getByRole("button", { name }));
}

async function rowOf(number: string): Promise<HTMLElement> {
  const link = await screen.findByRole("link", { name: number });
  const row = link.closest("tr");
  if (row === null) throw new Error("no row");
  return row;
}

describe("Expense requests", () => {
  it("TEST-FE-1166 shows the open requests with their next step for the Accountant", async () => {
    show("exreqs", fakeApi());
    expect(
      await screen.findByText(
        "You approve requests up to $100.00. Above that, the Owner approves. You give advances, record bills and reimburse staff.",
      ),
    ).toBeInTheDocument();
    const wait = screen.getByRole("button", {
      name: /^Pending approval: 3/,
    });
    expect(wait).toHaveTextContent("$640.00 · 1 for you");
    expect(
      screen.getByRole("button", { name: /^Outstanding advances: \$60\.00/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /^Owed to staff: \$25\.00/,
      }),
    ).toBeInTheDocument();
    expect(
      within(await rowOf("ER270001")).getByRole("button", { name: "Approve" }),
    ).toBeInTheDocument();
    expect(await rowOf("ER270002")).toHaveTextContent("Pending Owner approval");
    expect(await rowOf("ER270003")).toHaveTextContent("Late");
    expect(
      within(await rowOf("ER270003")).getByRole("button", {
        name: "Record bill",
      }),
    ).toBeInTheDocument();
    expect(
      within(await rowOf("ER270004")).getByRole("button", {
        name: "Reimburse staff",
      }),
    ).toBeInTheDocument();
    expect(await rowOf("ER270005")).toHaveTextContent(
      "Someone else must approve",
    );
    expect(screen.queryByRole("link", { name: "ER270006" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "All requests" }));
    expect(await rowOf("ER270006")).toHaveTextContent("Void");
    fireEvent.click(wait);
    expect(screen.queryByRole("link", { name: "ER270003" })).toBeNull();
  });

  it("TEST-FE-1167 lets the Owner approve above the limit and shows Staff only their own", async () => {
    show("exreqs", fakeApi(), OWNER);
    expect(
      within(await rowOf("ER270002")).getByRole("button", { name: "Approve" }),
    ).toBeInTheDocument();
    cleanup();
    show("exreqs", fakeApi(), STAFF);
    expect(
      await screen.findByText(/You see only your own requests\./),
    ).toBeInTheDocument();
    expect(await rowOf("ER270001")).toHaveTextContent("Pending approval");
    expect(await rowOf("ER270004")).toHaveTextContent("Accountant's step");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("TEST-FE-1168 sends a request with its Unit, a new supplier and the advance", async () => {
    const api = fakeApi();
    show("exreqs", api);
    await press("New Expense request");
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(dialog).toHaveTextContent("Write why this is needed.");
    expect(dialog).toHaveTextContent("Type the amount.");
    expect(api.submitRequest).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText("Unit"), {
      target: { value: "unit-1" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Reason/), {
      target: { value: "Tap leaking" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "60" },
    });
    expect(dialog).toHaveTextContent(
      "Approved by: the Accountant (up to $100.00) or the Owner.",
    );
    fireEvent.change(within(dialog).getByLabelText("Supplier (if known)"), {
      target: { value: "Heng Electric" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(api.submitRequest).toHaveBeenCalledWith("prop-1", {
        kind: "REQUEST",
        account_code: "6050",
        description: "Tap leaking",
        reason: "Tap leaking",
        amount_cents: 6_000,
        currency: "USD",
        original_amount_minor: null,
        exchange_rate_record_id: null,
        supplier_id: "sup-new",
        unit_id: "unit-1",
        spent_on: null,
        paid_how: "ADVANCE",
        paid_from_code: null,
      });
    });
    expect(api.addSupplier).toHaveBeenCalledWith("prop-1", "Heng Electric");
    expect(
      await screen.findByText("ER270001 submitted for approval."),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe("#/exreqs/ER270001");
  });

  it("TEST-FE-1169 sends an Expense report in riel with today's rate and refuses an asset on an expense account", async () => {
    const api = fakeApi();
    show("exreqs", api);
    await press("New Expense report");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Reason/), {
      target: { value: "Pipe burst at night" },
    });
    fireEvent.change(within(dialog).getByLabelText("Currency"), {
      target: { value: "KHR" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "74,000" },
    });
    expect(dialog).toHaveTextContent("= $18.05 at 4,100 ៛ per $1");
    fireEvent.change(within(dialog).getByLabelText("Paid from"), {
      target: { value: "1030" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(api.submitRequest).toHaveBeenCalledWith(
        "prop-1",
        expect.objectContaining({
          kind: "URGENT_REPORT",
          amount_cents: 1_805,
          currency: "KHR",
          original_amount_minor: 74_000,
          exchange_rate_record_id: "rate-1",
          spent_on: "2027-02-10",
          paid_how: "CASH",
          paid_from_code: "1030",
        }) as unknown,
      );
    });
    cleanup();
    window.location.hash = "";
    const again = fakeApi();
    show("exreqs", again);
    await press("New Expense request");
    const second = await screen.findByRole("dialog");
    fireEvent.change(within(second).getByLabelText(/Reason/), {
      target: { value: "New fridge" },
    });
    fireEvent.change(within(second).getByLabelText(/^Amount/), {
      target: { value: "520" },
    });
    fireEvent.click(within(second).getByRole("button", { name: "Send" }));
    expect(second).toHaveTextContent(
      "For $500.00 or more, choose an asset account (business rule).",
    );
    expect(again.submitRequest).not.toHaveBeenCalled();
  });

  it("TEST-FE-1170 approves, gives an advance and records the bill with the entry numbers", async () => {
    const api = fakeApi({
      request: vi.fn(() =>
        Promise.resolve({ ...DETAIL, status: "PAID_OUT" as const }),
      ),
    });
    show("exreqs", api);
    fireEvent.click(
      within(await rowOf("ER270001")).getByRole("button", { name: "Approve" }),
    );
    let dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "$60.00 for Repairs and maintenance. Requested by Chan Sophea.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("ER270001 approved.")).toBeInTheDocument();
    expect(api.decide).toHaveBeenCalledWith("prop-1", "r-1", true, null);
    fireEvent.click(
      within(await rowOf("ER270003")).getByRole("button", {
        name: "Record bill",
      }),
    );
    dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Advance given: $60.00.");
    fireEvent.change(within(dialog).getByLabelText(/Bill amount/), {
      target: { value: "50" },
    });
    expect(dialog).toHaveTextContent("Unspent cash returned: $10.00");
    fireEvent.change(within(dialog).getByLabelText("Reference"), {
      target: { value: "SH-2210" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record bill" }),
    );
    expect(
      await screen.findByText(
        "Bill recorded as expense EX270004. Entry JE270011.",
      ),
    ).toBeInTheDocument();
    expect(api.recordBill).toHaveBeenCalledWith("prop-1", "r-3", {
      spent_cents: 5_000,
      spent_on: "2027-02-10",
      bill_number: "SH-2210",
      supplier_id: null,
      due_date: null,
    });
  });

  it("TEST-FE-1171 pays staff back from the chosen money account with the entry number", async () => {
    const api = fakeApi({
      voidRequest: vi.fn(() =>
        Promise.reject(new LedgerError(422, "This request is already done")),
      ),
      request: vi.fn(() =>
        Promise.resolve({
          ...DETAIL,
          paybacks: [
            {
              paid_on: "2027-02-10",
              amount_cents: 2_500,
              from_code: "1010",
              entry_number: "JE270012",
              by_name: "Sok Chenda",
            },
          ],
        }),
      ),
    });
    show("exreqs", api);
    fireEvent.click(
      within(await rowOf("ER270004")).getByRole("button", {
        name: "Reimburse staff",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Reimburse Chan Sophea: $25.00 · ER270004",
    );
    fireEvent.change(within(dialog).getByLabelText("Pay from"), {
      target: { value: "1020" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Reimburse staff" }),
    );
    expect(
      await screen.findByText("Reimbursed. Entry JE270012."),
    ).toBeInTheDocument();
    expect(api.payBack).toHaveBeenCalledWith(
      "prop-1",
      "r-4",
      "1020",
      "2027-02-10",
    );
  });

  it("TEST-FE-1172 opens one request from the address with its steps and entries", async () => {
    window.location.hash = "#/exreqs/ER270003";
    const api = fakeApi();
    show("exreqs", api);
    expect(await screen.findByText("Sent by Chan Sophea")).toBeInTheDocument();
    expect(api.request).toHaveBeenCalledWith("prop-1", "ER270003");
    expect(screen.getByText("Approved by Sok Chenda")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Advance of $60.00 given by Sok Chenda from 1010 · Cash on hand (USD)",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bill of $50.00 recorded by Sok Chenda"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Unspent cash returned: $10.00"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Entry JE270011" }),
    ).toHaveAttribute("href", "#/journal/JE270011");
    expect(
      screen.getByText(
        "Approved by: the Accountant (up to $100.00) or the Owner.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1173 says when a request is not there", async () => {
    window.location.hash = "#/exreqs/ER279999";
    show(
      "exreqs",
      fakeApi({
        request: vi.fn(() => Promise.reject(new LedgerError(404, null))),
      }),
    );
    expect(
      await screen.findByText(
        "This request is not there, or you cannot see it.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1174 void shows a server refusal and keeps the dialog open", async () => {
    window.location.hash = "#/exreqs/ER270001";
    const api = fakeApi({
      request: vi.fn(() => Promise.resolve({ ...DETAIL, ...req({}) })),
      voidRequest: vi.fn(() =>
        Promise.reject(new LedgerError(409, "This request is already done")),
      ),
    });
    show("exreqs", api);
    await press("Void");
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Void" }));
    expect(dialog).toHaveTextContent("Write why this is needed.");
    fireEvent.change(within(dialog).getByLabelText(/Reason/), {
      target: { value: "Sent twice" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Void" }));
    expect(
      await within(dialog).findByText(
        "This could not be completed: This request is already done",
      ),
    ).toBeInTheDocument();
    expect(api.voidRequest).toHaveBeenCalledWith("prop-1", "r-1", "Sent twice");
  });

  it("TEST-FE-1175 shows Khmer words when the screen is in Khmer", async () => {
    show("exreqs", fakeApi(), ACCOUNTANT, "km");
    expect((await screen.findAllByText("សំណើចំណាយ")).length).toBeGreaterThan(0);
    expect(await rowOf("ER270001")).toHaveTextContent("ការជួសជុល និងថែទាំ");
  });
});

describe("Expenses", () => {
  it("TEST-FE-1176 lists expenses with their entry, request and pay-later marks", async () => {
    show("expenses", fakeApi());
    expect(
      await screen.findByRole("link", { name: "EX270004" }),
    ).toHaveAttribute("href", "#/journal/JE270011");
    expect(screen.getByRole("link", { name: "ER270003" })).toHaveAttribute(
      "href",
      "#/exreqs/ER270003",
    );
    expect(await rowOf("EX270003")).toHaveTextContent(
      "Pay later (supplier bill)",
    );
  });

  it("TEST-FE-1177 records a bill paid at once and needs a supplier and amount", async () => {
    const api = fakeApi();
    show("expenses", api);
    await press("Record a bill");
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent("Type the supplier.");
    expect(dialog).toHaveTextContent("Type the amount.");
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "1,177" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Supplier\s?Required$/), {
      target: { value: "sok hardware" },
    });
    fireEvent.change(within(dialog).getByLabelText("Reference"), {
      target: { value: "EDC 01/2027" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordExpense).toHaveBeenCalledWith("prop-1", {
        expense_date: "2027-02-10",
        account_code: "6010",
        description: "EDC 01/2027",
        amount_cents: 117_700,
        paid_from_code: "1020",
        supplier_id: "sup-1",
        bill_number: "EDC 01/2027",
        due_date: null,
        unit_id: null,
      });
    });
    expect(api.addSupplier).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Expense EX270003 recorded. Entry JE270009."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1178 hides Record a bill without the right", async () => {
    show("expenses", fakeApi(), new Set(["ledger.read"]));
    await screen.findByRole("link", { name: "EX270004" });
    expect(screen.queryByRole("button", { name: "Record a bill" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Void" })).toBeNull();
  });

  it("TEST-FE-1209 voids an expense with a reason and shows the reversing entry", async () => {
    const voided: ExpenseRow = {
      ...at(EXPENSES, 0),
      status: "VOID",
      void_reason: "Recorded twice",
      voided_by_name: "Sok Chenda",
      voided_at: "2027-02-10T03:00:00+00:00",
      void_entry_number: "JE270020",
    };
    const expenses = vi
      .fn<SpendingApi["expenses"]>()
      .mockResolvedValueOnce(EXPENSES)
      .mockResolvedValue([voided, at(EXPENSES, 1)]);
    const api = fakeApi({ expenses });
    show("expenses", api);
    await screen.findByRole("link", { name: "EX270004" });
    expect(
      screen.getByText("Reverse the payments of bill SB270001 first"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Void" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Sok Hardware · $50.00 · paid from 1400 · Staff advances",
    );
    expect(dialog).toHaveTextContent("1400 · debit $50.00");
    expect(dialog).toHaveTextContent("6050 · credit $50.00");
    fireEvent.click(within(dialog).getByRole("button", { name: "Void" }));
    expect(
      await within(dialog).findByText("Enter a reason."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Recorded twice" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Void" }));
    expect(
      await screen.findByText("EX270004 voided. Reversing entry JE270020."),
    ).toBeInTheDocument();
    expect(api.voidExpense).toHaveBeenCalledWith(
      "prop-1",
      "x-1",
      "Recorded twice",
    );
    expect(
      await screen.findByText(/^Voided by Sok Chenda · .* · Recorded twice$/),
    ).toBeInTheDocument();
  });
});

describe("Supplier bills", () => {
  it("TEST-FE-1179 shows bills to pay with late days and paid bills", async () => {
    show("bills", fakeApi());
    expect(
      await screen.findByRole("button", { name: /^Still to pay: \$265\.00/ }),
    ).toBeInTheDocument();
    const late = screen.getByRole("button", {
      name: /^Overdue: \$220\.00/,
    });
    expect(screen.getByText("SB270001").closest("tr")).toHaveTextContent(
      "11 days overdue",
    );
    expect(screen.getByText("SB270002").closest("tr")).toHaveTextContent(
      "Not yet due",
    );
    fireEvent.click(late);
    expect(screen.queryByText("SB270002")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Paid: 1/ }));
    expect(screen.getByText("SB270003").closest("tr")).toHaveTextContent(
      "Paid",
    );
  });

  it("TEST-FE-1180 pays a bill in part and not more than is left", async () => {
    const api = fakeApi();
    show("bills", api);
    await screen.findByText("SB270002");
    const row = screen.getByText("SB270002").closest("tr");
    if (row === null) throw new Error("no row");
    fireEvent.click(within(row).getByRole("button", { name: "Pay" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Sok Hardware · Balance due $45.00");
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Pay" }));
    expect(dialog).toHaveTextContent("You can pay $45.00 or less.");
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "20" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Pay" }));
    await waitFor(() => {
      expect(api.payBill).toHaveBeenCalledWith("prop-1", "b-2", {
        from_code: "1020",
        paid_on: "2027-02-10",
        amount_cents: 2_000,
      });
    });
    expect(
      await screen.findByText("Bill SB270002 paid. Entry JE270006."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1181 adds a supplier bill to pay later with its due date", async () => {
    const api = fakeApi();
    show("bills", api);
    await press("Add supplier bill");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Supplier\s?Required$/), {
      target: { value: "Lift Care Co." },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "220" },
    });
    fireEvent.change(within(dialog).getByLabelText("Supplier's bill number"), {
      target: { value: "LC-0931" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.recordExpense).toHaveBeenCalledWith("prop-1", {
        expense_date: "2027-02-10",
        account_code: "6010",
        description: "LC-0931",
        amount_cents: 22_000,
        paid_from_code: null,
        supplier_id: "sup-new",
        bill_number: "LC-0931",
        due_date: "2027-03-12",
        unit_id: null,
      });
    });
    expect(
      await screen.findByText("Supplier bill SB270001 added. Entry JE270009."),
    ).toBeInTheDocument();
    expect(
      at(screen.getAllByRole("button", { name: "Pay" }), 0),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1211 adds a new supplier once when the app refuses the first save", async () => {
    const recordExpense = vi
      .fn<SpendingApi["recordExpense"]>()
      .mockRejectedValueOnce(
        new LedgerError(422, "Account 6010 cannot take an expense"),
      )
      .mockResolvedValue("x-2");
    const api = fakeApi({ recordExpense });
    show("bills", api);
    await press("Add supplier bill");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Supplier\s?Required$/), {
      target: { value: "Mattress" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/Account 6010 cannot take an expense/),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(recordExpense).toHaveBeenCalledTimes(2);
    });
    expect(api.addSupplier).toHaveBeenCalledTimes(1);
    expect(recordExpense.mock.calls[1]?.[1].supplier_id).toBe("sup-new");
  });

  it("TEST-FE-1212 shows that the bills could not be read again instead of the old list", async () => {
    const bills = vi
      .fn<SpendingApi["bills"]>()
      .mockResolvedValueOnce([])
      .mockRejectedValue(new LedgerError(500, null));
    const api = fakeApi({ bills });
    show("bills", api);
    expect(
      await screen.findByText("No supplier bills here."),
    ).toBeInTheDocument();
    await press("Add supplier bill");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Supplier\s?Required$/), {
      target: { value: "Marady" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("This list could not be loaded. Try again."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No supplier bills here."),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1210 shows each payment under its bill and reverses one with a reason", async () => {
    const reversedBills: SupplierBill[] = BILLS.map((bill) =>
      bill.id === "b-2"
        ? {
            ...bill,
            still_to_pay_cents: bill.amount_cents,
            payments: bill.payments.map((payment) => ({
              ...payment,
              reversed: true,
              reversal_reason: "Paid twice",
              reversed_at: "2027-02-10T03:00:00+00:00",
              reversed_by_name: "Kompheak",
              reversal_entry_number: "JE270021",
            })),
          }
        : bill,
    );
    const bills = vi
      .fn<SpendingApi["bills"]>()
      .mockResolvedValueOnce(BILLS)
      .mockResolvedValue(reversedBills);
    const api = fakeApi({ bills });
    show("bills", api);
    await screen.findByText("SB270002");
    const row = screen.getByText("SB270002").closest("tr");
    if (row === null) throw new Error("no row");
    expect(row).toHaveTextContent(
      "Paid $100.00 on 05/02/2027 from 1020 · ABA Bank · USD account",
    );
    fireEvent.click(
      within(row).getByRole("button", { name: "Reverse payment" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("1020 · debit $100.00");
    expect(dialog).toHaveTextContent("2010 · credit $100.00");
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Paid twice" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Reverse payment" }),
    );
    expect(
      await screen.findByText("Payment on SB270002 reversed. Entry JE270021."),
    ).toBeInTheDocument();
    expect(api.reverseBillPayment).toHaveBeenCalledWith(
      "prop-1",
      "p-1",
      "Paid twice",
    );
    expect(
      await screen.findByText(/Reversed by Kompheak · .* · Paid twice/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reverse payment" }),
    ).toBeNull();
  });
});
