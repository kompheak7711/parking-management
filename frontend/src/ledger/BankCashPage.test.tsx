import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BankCashPage } from "./BankCashPage";
import type { BankCash, CashApi } from "./cashClient";

afterEach(() => {
  cleanup();
});

const OCTOBER = {
  id: "p-10",
  starts_on: "2026-10-01",
  ends_on: "2026-10-31",
  status: "OPEN",
  matched: false,
  counted: false,
};

const SEPTEMBER = {
  id: "p-09",
  starts_on: "2026-09-01",
  ends_on: "2026-09-30",
  status: "OPEN",
  matched: true,
  counted: true,
};

const BANK: BankCash["banks"][number] = {
  code: "1020",
  name_en: "ABA Bank · USD account",
  name_km: null,
  book_cents: 1_610_357,
  lines: [
    {
      line_id: "line-1",
      entry_number: "JE260563",
      entry_date: "2026-10-31",
      description: "Payment received",
      memo: "RCP260153",
      debit_cents: 45_795,
      credit_cents: 0,
    },
    {
      line_id: "line-2",
      entry_number: "JE260560",
      entry_date: "2026-10-20",
      description: "Expense EX260040",
      memo: null,
      debit_cents: 0,
      credit_cents: 1_000,
    },
  ],
  match: null,
};

const DATA: BankCash = {
  today: "2026-11-03",
  months: [OCTOBER, SEPTEMBER],
  month: OCTOBER,
  rate: { id: "rate-1", khr_per_usd: 4_100 },
  petty: {
    code: "1030",
    float_cents: 20_000,
    balance_cents: 15_550,
    waiting: [{ request_number: "ER260007", amount_cents: 2_800 }],
  },
  riel: {
    code: "1011",
    held_riel: 410_000,
    book_cents: 10_020,
    last_month_end: "2026-10-31",
    last_entry_number: "JE260565",
  },
  money_accounts: [
    {
      code: "1010",
      name_en: "Cash on hand (USD)",
      name_km: null,
      cash_kind: "CASH_USD",
      balance_cents: 50_000,
    },
    {
      code: "1011",
      name_en: "Cash on hand (KHR)",
      name_km: null,
      cash_kind: "CASH_KHR",
      balance_cents: 10_020,
    },
    {
      code: "1020",
      name_en: "ABA Bank · USD account",
      name_km: null,
      cash_kind: "BANK",
      balance_cents: 1_610_357,
    },
    {
      code: "1030",
      name_en: "Petty cash",
      name_km: null,
      cash_kind: "PETTY",
      balance_cents: 15_550,
    },
  ],
  banks: [BANK],
  cash: [
    {
      code: "1010",
      name_en: "Cash on hand (USD)",
      name_km: null,
      cash_kind: "CASH_USD",
      book_cents: 50_000,
      count: null,
    },
    {
      code: "1011",
      name_en: "Cash on hand (KHR)",
      name_km: null,
      cash_kind: "CASH_KHR",
      book_cents: 10_000,
      count: null,
    },
  ],
};

function fakeApi(extra: Partial<CashApi> = {}): CashApi {
  return {
    read: vi.fn(() => Promise.resolve(DATA)),
    entryOf: vi.fn(() => Promise.resolve("JE260570")),
    moveMoney: vi.fn(() => Promise.resolve("move-1")),
    ownerMoney: vi.fn(() => Promise.resolve("owner-1")),
    topUp: vi.fn(() => Promise.resolve("top-1")),
    countCash: vi.fn(() => Promise.resolve("count-1")),
    matchBank: vi.fn(() => Promise.resolve("match-1")),
    ...extra,
  };
}

function show(api: CashApi, capabilities: ReadonlySet<string> | null = null) {
  render(
    <BankCashPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      propertyId="prop-1"
    />,
  );
}

async function press(name: string | RegExp): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("button", { name })).toBeEnabled();
  });
  fireEvent.click(screen.getByRole("button", { name }));
}

describe("Bank and cash", () => {
  it("TEST-FE-1182 shows the petty cash float, the riel held and the month to match", async () => {
    const api = fakeApi();
    show(api);
    expect(await screen.findByText("$200.00")).toBeInTheDocument();
    expect(screen.getByText("$155.50")).toBeInTheDocument();
    expect(screen.getByText("$44.50")).toBeInTheDocument();
    expect(
      screen.getByText(/Bills not recorded yet: 1, \$28\.00/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ER260007" })).toHaveAttribute(
      "href",
      "#/exreqs/ER260007",
    );
    expect(screen.getByText("410,000 ៛")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "JE260565" })).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toHaveValue("2026-10-01");
    expect(
      screen.getByLabelText("ABA statement balance on 31/10/2026"),
    ).toHaveValue("16103.57");
    expect(api.read).toHaveBeenCalledWith("prop-1", null);
    fireEvent.change(screen.getByLabelText("Month"), {
      target: { value: "2026-09-01" },
    });
    await waitFor(() => {
      expect(api.read).toHaveBeenLastCalledWith("prop-1", "2026-09-01");
    });
  });

  it("TEST-FE-1183 matches the bank once the lines not on the statement are ticked", async () => {
    const api = fakeApi();
    show(api);
    const statement = await screen.findByLabelText(
      "ABA statement balance on 31/10/2026",
    );
    fireEvent.change(statement, { target: { value: "15,645.62" } });
    expect(screen.getByText("Does not match")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Mark as matched" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Not on the statement yet: JE260563",
      }),
    );
    expect(screen.getByText("-$457.95")).toBeInTheDocument();
    expect(screen.getByText("Matches")).toBeInTheDocument();
    await press("Mark as matched");
    await waitFor(() => {
      expect(api.matchBank).toHaveBeenCalledWith("prop-1", {
        account_code: "1020",
        period_id: "p-10",
        statement_balance_cents: 1_564_562,
        lines: [{ line_id: "line-2" }],
      });
    });
    expect(
      await screen.findByText("Bank matched for October 2026."),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1184 shows a matched month and a counted month as done", async () => {
    const done: BankCash = {
      ...DATA,
      month: SEPTEMBER,
      banks: [
        {
          ...BANK,
          lines: [],
          match: {
            statement_balance_cents: 1_500_000,
            status: "MATCHED",
            by_name: "Dara",
            at: "2026-10-02T09:00:00+07:00",
            lines: 4,
          },
        },
      ],
      cash: DATA.cash.map((account) => ({
        ...account,
        count: {
          counted_on: "2026-09-30",
          counted_cents: account.book_cents - 100,
          book_cents: account.book_cents,
          counted_riel: account.code === "1011" ? 40_590 : null,
          note: "Short at the till",
          entry_number: account.code === "1010" ? "JE260500" : null,
          by_name: "Dara",
          at: "2026-10-01T09:00:00+07:00",
        },
      })),
    };
    show(fakeApi({ read: vi.fn(() => Promise.resolve(done)) }));
    expect(await screen.findByText("Matched")).toBeInTheDocument();
    expect(screen.getByText(/^Done by Dara/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mark as matched" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cash count" }));
    expect(screen.getAllByText("Counted").length).toBeGreaterThan(1);
    expect(screen.getByRole("link", { name: "JE260500" })).toBeInTheDocument();
    expect(screen.getByText("40,590 ៛")).toBeInTheDocument();
    expect(screen.getByText("Reason: Short at the till")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save count" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1185 counts dollars and riel, and a difference needs a reason", async () => {
    const api = fakeApi();
    show(api);
    await press("Cash count");
    await press("Save count");
    expect(
      screen.getByText("Type what you counted in every box."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Counted 1010"), {
      target: { value: "499.00" },
    });
    fireEvent.change(screen.getByLabelText("Counted 1011"), {
      target: { value: "410,000" },
    });
    expect(screen.getByText("-$1.00")).toBeInTheDocument();
    await press("Save count");
    expect(screen.getByText("Say why.")).toBeInTheDocument();
    expect(api.countCash).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Reason for any difference"), {
      target: { value: "One dollar short" },
    });
    await press("Save count");
    expect(
      await screen.findByText("Cash count saved for October 2026."),
    ).toBeInTheDocument();
    expect(api.countCash).toHaveBeenNthCalledWith(1, "prop-1", {
      account_code: "1010",
      counted_on: "2026-10-31",
      counted_cents: 49_900,
      counted_riel: null,
      exchange_rate_record_id: null,
      reason: "One dollar short",
    });
    expect(api.countCash).toHaveBeenNthCalledWith(2, "prop-1", {
      account_code: "1011",
      counted_on: "2026-10-31",
      counted_cents: null,
      counted_riel: 410_000,
      exchange_rate_record_id: "rate-1",
      reason: null,
    });
  });

  it("TEST-FE-1186 moves money between places and says which entry it made", async () => {
    const api = fakeApi();
    show(api);
    await press("Move money");
    const dialog = await screen.findByRole("dialog");
    const from = within(dialog).getByLabelText("From");
    expect(
      within(from).queryByRole("option", { name: /1030/ }),
    ).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("To"), {
      target: { value: "1010" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move money" }));
    expect(dialog).toHaveTextContent("Pick two different places.");
    fireEvent.change(within(dialog).getByLabelText("To"), {
      target: { value: "1020" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "600" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move money" }));
    expect(dialog).toHaveTextContent("There is not that much money there.");
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "300" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move money" }));
    expect(
      await screen.findByText("Money moved. Entry JE260570."),
    ).toBeInTheDocument();
    expect(api.moveMoney).toHaveBeenCalledWith("prop-1", {
      moved_on: "2026-11-03",
      from_code: "1010",
      to_code: "1020",
      amount_cents: 30_000,
      received_cents: null,
      riel_amount_minor: null,
      exchange_rate_record_id: null,
    });
    expect(api.entryOf).toHaveBeenCalledWith("prop-1", "money-move", "move-1");
  });

  it("TEST-FE-1187 changes riel at the rate typed and shows the gain", async () => {
    const api = fakeApi();
    show(api);
    await press("Move money");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("From"), {
      target: { value: "1011" },
    });
    expect(
      within(dialog).getByLabelText("Rate (riel for 1 dollar)"),
    ).toHaveValue("4100");
    fireEvent.change(within(dialog).getByLabelText(/^Riel amount/), {
      target: { value: "205,000" },
    });
    fireEvent.change(
      within(dialog).getByLabelText("Rate (riel for 1 dollar)"),
      {
        target: { value: "4000" },
      },
    );
    expect(dialog).toHaveTextContent(
      "You get $51.25. The books hold this riel at $50.10. Exchange gain $1.15 goes to 4100.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Move money" }));
    await waitFor(() => {
      expect(api.moveMoney).toHaveBeenCalledWith("prop-1", {
        moved_on: "2026-11-03",
        from_code: "1011",
        to_code: "1020",
        amount_cents: 5_010,
        received_cents: 5_125,
        riel_amount_minor: 205_000,
        exchange_rate_record_id: "rate-1",
      });
    });
  });

  it("TEST-FE-1188 tops up petty cash only up to the float", async () => {
    const api = fakeApi();
    show(api);
    await press("Top up petty cash");
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Petty cash float $200.00. In petty cash now $155.50. You can add up to $44.50.",
    );
    expect(within(dialog).getByLabelText(/^Amount/)).toHaveValue("44.50");
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Top up" }));
    expect(dialog).toHaveTextContent(
      "That is more than the float allows, or more than there is to take.",
    );
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "44.50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Top up" }));
    expect(
      await screen.findByText("Petty cash topped up $44.50. Entry JE260570."),
    ).toBeInTheDocument();
    expect(api.topUp).toHaveBeenCalledWith("prop-1", {
      topped_up_on: "2026-11-03",
      from_code: "1010",
      amount_cents: 4_450,
    });
  });

  it("TEST-FE-1189 lets only the Owner record Owner money, with a note", async () => {
    const reader = fakeApi();
    show(reader, new Set(["ledger.read"]));
    await screen.findByText("$200.00");
    expect(
      screen.queryByRole("button", { name: "Owner money" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move money" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mark as matched" }),
    ).not.toBeInTheDocument();
    cleanup();
    const api = fakeApi();
    show(api, new Set(["ledger.read", "ledger.owner_money"]));
    await press("Owner money");
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/^Money out/));
    fireEvent.change(within(dialog).getByLabelText(/^Amount/), {
      target: { value: "100" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(dialog).toHaveTextContent("Say why.");
    fireEvent.change(within(dialog).getByLabelText(/^Note/), {
      target: { value: "Owner's school fees" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Owner money out $100.00. Entry JE260570."),
    ).toBeInTheDocument();
    expect(api.ownerMoney).toHaveBeenCalledWith("prop-1", {
      direction: "OUT",
      moved_on: "2026-11-03",
      account_code: "1020",
      amount_cents: 10_000,
      note: "Owner's school fees",
    });
  });
});
