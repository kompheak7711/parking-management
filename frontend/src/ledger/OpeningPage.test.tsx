import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChartPage } from "./ChartPage";
import type { Chart, LedgerApi } from "./ledgerClient";
import type { OpeningApi, OpeningLine, OpeningSheet } from "./openingClient";
import { OpeningBalances } from "./OpeningPage";

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

const ACCOUNTS = [
  {
    code: "1010",
    name_en: "Cash on hand (USD)",
    name_km: "សាច់ប្រាក់ក្នុងដៃ (USD)",
    account_type: "ASSET",
    normal_side: "DEBIT",
  },
  {
    code: "1020",
    name_en: "ABA Bank · USD account",
    name_km: null,
    account_type: "ASSET",
    normal_side: "DEBIT",
  },
  {
    code: "3000",
    name_en: "Owner's capital",
    name_km: null,
    account_type: "EQUITY",
    normal_side: "CREDIT",
  },
];

function line(
  code: string,
  name: string,
  debit: number,
  credit: number,
  memo: string | null = null,
): OpeningLine {
  return {
    account_code: code,
    name_en: name,
    name_km: null,
    debit_cents: debit,
    credit_cents: credit,
    memo,
  };
}

const NONE: OpeningSheet = {
  today: "2026-11-04",
  first_year: 2027,
  opening: null,
  accounts: ACCOUNTS,
  typed: [],
  worked_out: [],
  posted: [],
  needs_check: 0,
};

const DRAFT: OpeningSheet = {
  ...NONE,
  opening: {
    id: "ob-1",
    start_date: "2027-01-01",
    status: "DRAFT",
    entry_number: null,
    posted_by_name: null,
    posted_at: null,
  },
  typed: [line("1010", "Cash on hand (USD)", 50_000, 0, "Office cash")],
  worked_out: [
    line("1100", "Customer debt · Invoices", 120_000, 0),
    line("2100", "Security Deposits held", 0, 90_000),
  ],
};

const BALANCED: OpeningSheet = {
  ...DRAFT,
  typed: [
    ...DRAFT.typed,
    line("3000", "Owner's capital", 0, 80_000, "Start of the books"),
  ],
};

const POSTED: OpeningSheet = {
  ...BALANCED,
  opening: {
    id: "ob-1",
    start_date: "2027-01-01",
    status: "POSTED",
    entry_number: "JE270001",
    posted_by_name: "Kompheak",
    posted_at: "2027-01-02T03:00:00+00:00",
  },
  typed: [],
  worked_out: [],
  posted: [
    line("1010", "Cash on hand (USD)", 50_000, 0, "Opening balance"),
    line(
      "1100",
      "Customer debt · Invoices",
      120_000,
      0,
      "From the app's lists",
    ),
    line("2100", "Security Deposits held", 0, 90_000, "From the app's lists"),
    line("3000", "Owner's capital", 0, 80_000, "Opening balance"),
  ],
};

function fakeApi(
  sheet: OpeningSheet,
  extra: Partial<OpeningApi> = {},
): OpeningApi {
  return {
    read: vi.fn(() => Promise.resolve(sheet)),
    begin: vi.fn(() => Promise.resolve()),
    setLines: vi.fn(() => Promise.resolve()),
    post: vi.fn(() => Promise.resolve()),
    ...extra,
  };
}

function show(api: OpeningApi, canEdit = true, language: "en" | "km" = "en") {
  render(
    <OpeningBalances
      active
      api={api}
      canEdit={canEdit}
      language={language}
      propertyId="prop-1"
    />,
  );
}

describe("Opening balances", () => {
  it("TEST-FE-1213 lets the Owner start the books on 1 January of the first year", async () => {
    const read = vi
      .fn<OpeningApi["read"]>()
      .mockResolvedValueOnce(NONE)
      .mockResolvedValue(DRAFT);
    const api = fakeApi(NONE, { read });
    show(api);
    expect(
      await screen.findByRole("heading", { name: "Start the books" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^First year/)).toHaveValue("2027");
    expect(
      screen.getByText(
        "The books start on 1 January 2027. Opening balances are as at 31 December 2026.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^First year/), {
      target: { value: "20x7" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start the books" }));
    expect(
      await screen.findByText("Type a year such as 2027."),
    ).toBeInTheDocument();
    expect(api.begin).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^First year/), {
      target: { value: "2027" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start the books" }));
    expect(
      await screen.findByText(
        "The books start on 01/01/2027. Type the opening balances next.",
      ),
    ).toBeInTheDocument();
    expect(api.begin).toHaveBeenCalledWith("prop-1", 2027);
    expect(
      await screen.findByRole("heading", {
        name: /Books start on 01\/01\/2027/,
      }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1214 shows typed and worked-out lines, says how far off they are and keeps Post closed", async () => {
    show(fakeApi(DRAFT));
    expect(await screen.findByText("Not posted yet")).toBeInTheDocument();
    expect(screen.getByText("Office cash")).toBeInTheDocument();
    expect(screen.getByText("Customer debt · Invoices")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Debits and credits differ by $800.00. Put the difference on an equity account such as 3000 Owner's capital.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Post opening balances" }),
    ).toBeDisabled();
  });

  it("TEST-FE-1215 types the lines once each, one side each, and saves them whole", async () => {
    const api = fakeApi(DRAFT);
    show(api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Type the opening balances" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Debit")).toHaveValue("500.00");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Add account" }),
    );
    const accounts = within(dialog).getAllByLabelText("Account");
    const debits = within(dialog).getAllByLabelText("Debit");
    const credits = within(dialog).getAllByLabelText("Credit");
    // The same account twice, and a line with both sides, are refused.
    fireEvent.change(at(accounts, 1), { target: { value: "1010" } });
    fireEvent.change(at(debits, 1), { target: { value: "5" } });
    fireEvent.change(at(credits, 1), { target: { value: "5" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("Each account goes in once."),
    ).toBeInTheDocument();
    fireEvent.change(at(accounts, 1), { target: { value: "3000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "Type a debit or a credit, more than zero, not both.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(at(debits, 1), { target: { value: "" } });
    fireEvent.change(at(credits, 1), { target: { value: "800" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Opening balances saved."),
    ).toBeInTheDocument();
    expect(api.setLines).toHaveBeenCalledWith("prop-1", [
      {
        account_code: "1010",
        debit_cents: 50_000,
        credit_cents: 0,
        memo: "Office cash",
      },
      {
        account_code: "3000",
        debit_cents: 0,
        credit_cents: 80_000,
        memo: null,
      },
    ]);
  });

  it("TEST-FE-1216 posts balanced opening balances after the Owner confirms", async () => {
    const read = vi
      .fn<OpeningApi["read"]>()
      .mockResolvedValueOnce(BALANCED)
      .mockResolvedValue(POSTED);
    const api = fakeApi(BALANCED, { read });
    show(api);
    expect(await screen.findByText("Balanced")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Post opening balances" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "This posts one entry dated 01/01/2027. After that the opening balances are locked",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Post opening balances" }),
    );
    expect(
      await screen.findByText("Opening balances posted."),
    ).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("prop-1");
    expect(await screen.findByText("Locked")).toBeInTheDocument();
  });

  it("TEST-FE-1217 shows posted opening balances locked with their entry and who posted them", async () => {
    show(fakeApi(POSTED));
    expect(await screen.findByText("Locked")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Entry JE270001" }),
    ).toHaveAttribute("href", "#/journal/JE270001");
    expect(screen.getByText(/^Posted by Kompheak/)).toBeInTheDocument();
    expect(screen.getAllByText("$1,700.00")).toHaveLength(2);
    expect(
      screen.getByText(
        "Opening balances are locked once posted. A later fix goes in as an adjusting entry.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Type the opening balances" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1290 says why Post is closed before anything is typed", async () => {
    show(fakeApi({ ...DRAFT, typed: [], worked_out: [] }));
    expect(
      await screen.findByText(
        "Enter the opening balances first. You can post when total debits equal total credits.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Post opening balances" }),
    ).toBeDisabled();
  });

  it("TEST-FE-1218 holds posting while records wait in Needs check and shows the Owner-only note to others", async () => {
    show(fakeApi({ ...BALANCED, needs_check: 3 }));
    expect(
      await screen.findByText(
        /3 records are in Unposted records\. Clear that list before you post\./,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Post opening balances" }),
    ).toBeDisabled();
    cleanup();
    show(fakeApi(NONE), false);
    expect(
      await screen.findByText(
        "Only the Owner starts the books and types the opening balances.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Start the books" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1219 opens from the Chart of accounts button and its address", async () => {
    const chart: Chart = { as_of: "2027-01-31", accounts: [] };
    const ledger = {
      accounts: vi.fn(() => Promise.resolve(chart)),
    } as unknown as LedgerApi;
    const opening = fakeApi(DRAFT);
    const { rerender } = render(
      <ChartPage
        active
        api={ledger}
        capabilities={new Set(["ledger.read"])}
        language="en"
        openingApi={opening}
        propertyId="prop-1"
      />,
    );
    const button = await screen.findByRole("link", {
      name: "Opening balances",
    });
    expect(button).toHaveAttribute("href", "#/chart/opening");
    window.location.hash = "#/chart/opening";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    rerender(
      <ChartPage
        active
        api={ledger}
        capabilities={new Set(["ledger.read"])}
        language="en"
        openingApi={opening}
        propertyId="prop-1"
      />,
    );
    await waitFor(() => {
      expect(opening.read).toHaveBeenCalledWith("prop-1");
    });
    expect(
      await screen.findByRole("heading", { name: "Opening balances" }),
    ).toBeInTheDocument();
    // Without ledger.opening_balances the lines are shown but cannot be typed.
    expect(
      screen.queryByRole("button", { name: "Type the opening balances" }),
    ).not.toBeInTheDocument();
  });
});
