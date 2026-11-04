import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type Account,
  type Chart,
  type Entry,
  type Journal,
  LedgerError,
  type LedgerApi,
  type MethodAccount,
  type PostingProblem,
  type Report,
} from "./ledgerClient";
import { LedgerPage, type LedgerTab } from "./LedgerPage";

beforeEach(() => {
  window.location.hash = "";
});

function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`missing item ${String(index)}`);
  return item;
}

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

function account(extra: Partial<Account>): Account {
  return {
    code: "1010",
    name_en: "Cash on hand (USD)",
    name_km: "សាច់ប្រាក់ក្នុងដៃ (USD)",
    account_type: "ASSET",
    control_source: null,
    tax_locked: false,
    active: true,
    used: true,
    balance_cents: 116481,
    ...extra,
  };
}

const CHART: Chart = {
  as_of: "2027-01-31",
  accounts: [
    account({}),
    account({
      code: "1020",
      name_en: "ABA Bank · USD account",
      name_km: null,
      balance_cents: 1654687,
    }),
    account({
      code: "1100",
      name_en: "Customer debt · Invoices",
      control_source: "INVOICES",
      balance_cents: 615725,
    }),
    account({
      code: "2400",
      name_en: "Taxes to pay",
      account_type: "LIABILITY",
      tax_locked: true,
      used: false,
      balance_cents: 0,
    }),
    account({
      code: "4010",
      name_en: "Rent",
      name_km: "ឈ្នួល",
      account_type: "INCOME",
      balance_cents: 2504000,
    }),
  ],
};

const JOURNAL: Journal = {
  month: null,
  months: ["2027-01-01"],
  newest_only: true,
  entries: [
    {
      entry_number: "JE270002",
      entry_date: "2027-01-25",
      entry_kind: "AUTO",
      description: "Invoice INV270001 issued",
      source_type: "INVOICE",
      source_number: "INV270001",
      source_link: { page: "invoices", detail: "inv:i-1" },
      amount_cents: 42300,
      reverses: null,
      reversed_by: null,
    },
    {
      entry_number: "JE270001",
      entry_date: "2027-01-08",
      entry_kind: "AUTO",
      description: "Expense EX270001: EDC",
      source_type: "EXPENSE",
      source_number: "EX270001",
      source_link: null,
      amount_cents: 117700,
      reverses: null,
      reversed_by: "JE270003",
    },
  ],
};

const ENTRY: Entry = {
  ...at(JOURNAL.entries, 0),
  reason: null,
  posted_at: "2027-01-25T16:50:00Z",
  posted_by_name: null,
  approved_by_name: null,
  month_closed: false,
  lines: [
    {
      account_code: "1100",
      account_name_en: "Customer debt · Invoices",
      account_name_km: null,
      debit_cents: 42300,
      credit_cents: 0,
      memo: "INV270001",
    },
    {
      account_code: "4010",
      account_name_en: "Rent",
      account_name_km: "ឈ្នួល",
      debit_cents: 0,
      credit_cents: 42300,
      memo: null,
    },
  ],
};

const PROBLEMS: PostingProblem[] = [
  {
    posting_key: "payment:p-1",
    source_type: "PAYMENT",
    source_id: "p-1",
    event_date: "2027-01-12",
    problem: "No ledger account is set for the Payment Method KHQR",
    first_seen_at: "2027-01-12T03:00:00Z",
    source_number: "RCP270004",
    source_link: { page: "payments", detail: "receipt:p-1" },
  },
  {
    posting_key: "invoice:i-9:issue",
    source_type: "INVOICE",
    source_id: "i-9",
    event_date: "2027-01-13",
    problem:
      'new row for relation "gl_journal_lines" violates check constraint',
    first_seen_at: "2027-01-13T03:00:00Z",
    source_number: "INV270009",
    source_link: { page: "invoices", detail: "inv:i-9" },
  },
];

const METHODS: MethodAccount[] = [
  {
    kind: "PAYMENT",
    method_id: "m-cash",
    code: "CASH",
    name: "Cash",
    account_code: "1010",
    account_name: "Cash on hand (USD)",
    effective_from: "2027-01-01",
  },
  {
    kind: "PAYMENT",
    method_id: "m-khqr",
    code: "KHQR",
    name: "KHQR",
    account_code: null,
    account_name: null,
    effective_from: null,
  },
  {
    kind: "REFUND",
    method_id: "r-cash",
    code: "CASH",
    name: "Cash",
    account_code: "1010",
    account_name: "Cash on hand (USD)",
    effective_from: "2027-01-01",
  },
];

const PROFIT: Report = {
  report: "profit-and-loss",
  title: "Profit and loss",
  period: "January 2027",
  state: "Open, may still change",
  columns: [
    { key: "code", label: "Account", kind: "text" },
    { key: "name", label: "Name", kind: "text" },
    { key: "this_month", label: "This month", kind: "money" },
  ],
  rows: [
    { line: "heading", code: null, name: "Income" },
    { line: "account", code: "4010", name: "Rent", this_month: 42300 },
    { line: "total", code: null, name: "Total income", this_month: 42300 },
  ],
  check: { ok: true, text: "Profit matches the Balance sheet" },
};

function fakeApi(extra: Partial<LedgerApi> = {}): LedgerApi {
  return {
    accounts: vi.fn(() => Promise.resolve(CHART)),
    entries: vi.fn(() => Promise.resolve(JOURNAL)),
    entry: vi.fn(() => Promise.resolve(ENTRY)),
    needsCheck: vi.fn(() => Promise.resolve(PROBLEMS)),
    methodAccounts: vi.fn(() => Promise.resolve(METHODS)),
    setMethodAccount: vi.fn(() => Promise.resolve(METHODS)),
    report: vi.fn(() => Promise.resolve(PROFIT)),
    reportFile: vi.fn(() =>
      Promise.resolve({ fileName: "profit-and-loss.xlsx", file: new Blob() }),
    ),
    booksCheck: vi.fn(() =>
      Promise.resolve([
        {
          check_code: "CUSTOMER_DEBT",
          accounts: "1100 + 1110",
          in_books: 615725,
          in_list: 615725,
          ok: true,
        },
        {
          check_code: "EVERY_RECORD_POSTED",
          accounts: null,
          in_books: 0,
          in_list: 2,
          ok: false,
        },
      ]),
    ),
    ...extra,
  };
}

function show(
  tab: LedgerTab,
  api: LedgerApi,
  capabilities: ReadonlySet<string> | null = new Set(["ledger.read"]),
  language: "en" | "km" = "en",
) {
  return render(
    <LedgerPage
      active
      api={api}
      capabilities={capabilities}
      language={language}
      propertyId="prop-1"
      tab={tab}
    />,
  );
}

describe("Journal entries", () => {
  it("TEST-FE-1190 lists entries newest first with the record they came from", async () => {
    const api = fakeApi();
    show("journal", api);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("JE270002");
    expect(rows[1]).toHaveTextContent("Invoice issued");
    expect(rows[1]).toHaveTextContent("$423.00");
    expect(
      within(at(rows, 1)).getByRole("link", { name: "INV270001" }),
    ).toHaveAttribute("href", "#/invoices/inv%3Ai-1");
    expect(rows[2]).toHaveTextContent("EX270001");
    expect(screen.getByText(/Newest 2 entries/)).toBeInTheDocument();
  });

  it("TEST-FE-1191 reads one month when a month is picked", async () => {
    const api = fakeApi();
    show("journal", api);
    const month = await screen.findByLabelText("Month");
    fireEvent.change(month, { target: { value: "2027-01-01" } });
    await waitFor(() => {
      expect(api.entries).toHaveBeenLastCalledWith("prop-1", "2027-01-01");
    });
  });

  it("TEST-FE-1192 opens one entry from the address with its lines and totals", async () => {
    window.location.hash = "#/journal/JE270002";
    const api = fakeApi();
    show("journal", api);
    expect(
      await screen.findByRole("heading", { name: "JE270002" }),
    ).toBeInTheDocument();
    expect(api.entry).toHaveBeenCalledWith("prop-1", "JE270002");
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("1100 · Customer debt · Invoices");
    expect(within(table).getAllByText("$423.00").length).toBeGreaterThanOrEqual(
      4,
    );
    expect(screen.getByText(/Recorded by: The app/)).toBeInTheDocument();
  });

  it("TEST-FE-1193 says when the entry is not in the ledger", async () => {
    window.location.hash = "#/journal/JE279999";
    show(
      "journal",
      fakeApi({
        entry: vi.fn(() => Promise.reject(new LedgerError(404))),
      }),
    );
    expect(
      await screen.findByText("This entry is not in the ledger."),
    ).toBeInTheDocument();
  });
});

describe("Chart of accounts", () => {
  it("TEST-FE-1194 groups accounts by type with their balance and marks", async () => {
    show("chart", fakeApi());
    const assets = await screen.findByRole("heading", { name: "Assets" });
    expect(assets).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Liabilities" }),
    ).toBeInTheDocument();
    expect(screen.getByText("App records only")).toBeInTheDocument();
    expect(screen.getByText("No entries yet")).toBeInTheDocument();
    expect(screen.getByText("$16,546.87")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "4010" })).toHaveAttribute(
      "href",
      "#/chart/4010",
    );
  });

  it("TEST-FE-1157 shows Khmer account names when the screen is in Khmer", async () => {
    show("chart", fakeApi(), new Set(["ledger.read"]), "km");
    expect(await screen.findByText("ឈ្នួល")).toBeInTheDocument();
    // An account with no Khmer name keeps its English name.
    expect(screen.getByText("ABA Bank · USD account")).toBeInTheDocument();
  });

  it("TEST-FE-1158 opens an account with every line and the running balance", async () => {
    window.location.hash = "#/chart/1010";
    const api = fakeApi({
      report: vi.fn(() =>
        Promise.resolve<Report>({
          ...PROFIT,
          report: "account-detail",
          columns: [],
          rows: [
            {
              line: "total",
              entry_date: "2027-01-01",
              entry_number: null,
              balance: 0,
            },
            {
              line: "account",
              entry_date: "2027-01-08",
              entry_number: "JE270001",
              description: "Cash sale",
              debit: 5000,
              credit: null,
              balance: 5000,
            },
          ],
        }),
      ),
    });
    show("chart", api);
    expect(
      await screen.findByRole("link", { name: "JE270001" }),
    ).toHaveAttribute("href", "#/journal/JE270001");
    expect(api.report).toHaveBeenCalledWith("prop-1", "account-detail", {
      account: "1010",
      from: undefined,
      to: undefined,
    });
    expect(screen.getByText("Opening balance")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This account has entries, so it can be turned off but never deleted.",
      ),
    ).toBeInTheDocument();
  });
});

describe("Needs check", () => {
  it("TEST-FE-1159 lists records waiting with a reason in the screen's words only", async () => {
    show("needscheck", fakeApi());
    expect(
      await screen.findByText(
        "No ledger account is set for the Payment Method KHQR",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/violates check constraint/)).toBeNull();
    expect(
      screen.getByText(/The ledger could not post this record/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "RCP270004" })).toHaveAttribute(
      "href",
      "#/payments/receipt%3Ap-1",
    );
    // Only the Owner (ledger.accounts.manage) sets accounts.
    expect(
      screen.queryByRole("button", { name: "Set the account" }),
    ).toBeNull();
    expect(
      screen.getAllByText("Only the Owner sets these accounts.").length,
    ).toBe(2);
  });

  it("TEST-FE-1160 lets the Owner set a method's account from a date", async () => {
    const api = fakeApi();
    show("needscheck", api, new Set(["ledger.read", "ledger.accounts.manage"]));
    const buttons = await screen.findAllByRole("button", {
      name: "Set the account",
    });
    fireEvent.click(at(buttons, 0));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Ledger account for KHQR");
    fireEvent.change(within(dialog).getByLabelText(/Account/), {
      target: { value: "1020" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.setMethodAccount).toHaveBeenCalledWith(
        "prop-1",
        expect.objectContaining({
          kind: "PAYMENT",
          method_id: "m-khqr",
          account_code: "1020",
        }),
      );
    });
    expect(
      await screen.findByText("KHQR now uses account 1020."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1161 says when nothing waits", async () => {
    show(
      "needscheck",
      fakeApi({ needsCheck: vi.fn(() => Promise.resolve([])) }),
    );
    expect(
      await screen.findByText(
        "Nothing to check. Every money record is in the ledger.",
      ),
    ).toBeInTheDocument();
  });
});

describe("Financial statements", () => {
  it("TEST-FE-1162 shows a statement with its state and check line", async () => {
    const api = fakeApi();
    show("statements", api);
    expect(
      await screen.findByRole("heading", { name: "Profit and loss" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Open, may still change")).toBeInTheDocument();
    expect(
      screen.getByText(/Profit matches the Balance sheet/),
    ).toBeInTheDocument();
    expect(api.report).toHaveBeenCalledWith(
      "prop-1",
      "profit-and-loss",
      expect.objectContaining({
        month: expect.stringMatching(/-01$/) as unknown,
      }),
    );
  });

  it("TEST-FE-1163 asks each statement for its own values", async () => {
    const api = fakeApi();
    show("statements", api);
    await screen.findByRole("heading", { name: "Profit and loss" });
    fireEvent.click(screen.getByRole("button", { name: "Balance sheet" }));
    await waitFor(() => {
      expect(api.report).toHaveBeenLastCalledWith(
        "prop-1",
        "balance-sheet",
        expect.objectContaining({ as_of: expect.any(String) as unknown }),
      );
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Customer debt aging" }),
    );
    await waitFor(() => {
      expect(api.report).toHaveBeenLastCalledWith(
        "prop-1",
        "customer-aging",
        {},
      );
    });
  });

  it("TEST-FE-1164 downloads Excel and PDF files", async () => {
    const api = fakeApi();
    const created = vi.fn(() => "blob:x");
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    show("statements", api);
    await screen.findByRole("heading", { name: "Profit and loss" });
    fireEvent.click(screen.getByRole("button", { name: "Export Excel" }));
    expect(
      await screen.findByText("Downloaded profit-and-loss.xlsx."),
    ).toBeInTheDocument();
    expect(api.reportFile).toHaveBeenCalledWith(
      "prop-1",
      "profit-and-loss",
      expect.objectContaining({ month: expect.any(String) as unknown }),
      "xlsx",
    );
    fireEvent.click(screen.getByRole("button", { name: "Export PDF (A4)" }));
    await waitFor(() => {
      expect(api.reportFile).toHaveBeenLastCalledWith(
        "prop-1",
        "profit-and-loss",
        expect.any(Object),
        "pdf",
      );
    });
  });

  it("TEST-FE-1165 shows the Books check lines", async () => {
    const api = fakeApi();
    show("statements", api);
    await screen.findByRole("heading", { name: "Profit and loss" });
    fireEvent.click(screen.getByRole("button", { name: "Books check" }));
    expect(
      await screen.findByText("Every app money record has its entry"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 waiting")).toBeInTheDocument();
    expect(screen.getByText("Does not match")).toBeInTheDocument();
  });
});
