import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Budget, BudgetApi, BudgetSheet } from "./budgetClient";
import { BudgetPage } from "./BudgetPage";

afterEach(() => {
  cleanup();
});

const ACCOUNTANT_ID = "actor-accountant";
const OWNER_ID = "actor-owner";

const RENT = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((month) => ({
  account_code: "4010",
  month_no: month,
  amount_cents: 300_000,
}));

const REPAIRS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((month) => ({
  account_code: "6050",
  month_no: month,
  amount_cents: 20_000,
}));

const WAITING: Budget = {
  id: "b-2",
  version: 2,
  status: "DRAFT",
  created_by: ACCOUNTANT_ID,
  created_by_name: "Sok Chenda",
  created_at: "2026-11-02T08:40:00+00:00",
  approved_by_name: null,
  approved_at: null,
  decision_note: null,
  own_note: null,
  lines: [...RENT, ...REPAIRS],
};

const SHEET: BudgetSheet = {
  today: "2026-11-04",
  years: [
    { fiscal_year: 2026, status: "OPEN" },
    { fiscal_year: 2027, status: "OPEN" },
  ],
  year: 2027,
  accounts: [
    {
      code: "4010",
      name_en: "Rent income",
      name_km: null,
      account_type: "INCOME",
    },
    {
      code: "6050",
      name_en: "Repairs and maintenance",
      name_km: null,
      account_type: "EXPENSE",
    },
    {
      code: "6010",
      name_en: "Electricity bill (EDC)",
      name_km: null,
      account_type: "EXPENSE",
    },
  ],
  budgets: [WAITING],
  earlier_lines: [],
};

function fakeApi(extra: Partial<BudgetApi> = {}): BudgetApi {
  return {
    read: vi.fn(() => Promise.resolve(SHEET)),
    send: vi.fn(() => Promise.resolve()),
    decide: vi.fn(() => Promise.resolve()),
    ...extra,
  };
}

const OWNER = new Set([
  "ledger.read",
  "ledger.budgets.prepare",
  "ledger.budgets.approve",
]);
const ACCOUNTANT = new Set(["ledger.read", "ledger.budgets.prepare"]);

function show(
  api: BudgetApi,
  capabilities: ReadonlySet<string>,
  actorId: string,
) {
  render(
    <BudgetPage
      active
      actorId={actorId}
      api={api}
      capabilities={capabilities}
      language="en"
      propertyId="prop-1"
    />,
  );
}

describe("Budget", () => {
  it("TEST-FE-1203 shows a waiting budget by month with totals and lets the Owner approve it", async () => {
    const api = fakeApi();
    show(api, OWNER, OWNER_ID);
    expect(
      await screen.findByRole("heading", { name: "Budget 2027" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Waits for the Owner")).toBeInTheDocument();
    expect(screen.getByText(/^Prepared by Sok Chenda/)).toBeInTheDocument();
    const income = screen.getByRole("row", { name: /^Total income/ });
    expect(within(income).getByText("$36,000.00")).toBeInTheDocument();
    const profit = screen.getByRole("row", { name: /^Profit/ });
    expect(within(profit).getAllByText("$2,800.00")).toHaveLength(12);
    expect(within(profit).getByText("$33,600.00")).toBeInTheDocument();
    expect(screen.queryByText(/6010/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve budget" }));
    expect(
      await screen.findByText("Budget 2027 approved."),
    ).toBeInTheDocument();
    expect(api.decide).toHaveBeenCalledWith("prop-1", "b-2", true, null);
  });

  it("TEST-FE-1204 sends a budget back with a reason", async () => {
    const api = fakeApi();
    show(api, OWNER, OWNER_ID);
    fireEvent.click(await screen.findByRole("button", { name: "Send back" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(await within(dialog).findByText("Say why.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Repairs look low" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(
      await screen.findByText("Budget 2027 sent back."),
    ).toBeInTheDocument();
    expect(api.decide).toHaveBeenCalledWith(
      "prop-1",
      "b-2",
      false,
      "Repairs look low",
    );
  });

  it("TEST-FE-1205 tells the sender someone else must approve", async () => {
    show(fakeApi(), OWNER, ACCOUNTANT_ID);
    expect(
      await screen.findByText(
        "You sent this budget. Someone else must approve it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve budget" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1206 lets the Accountant type a sent-back budget again and send it", async () => {
    const back: BudgetSheet = {
      ...SHEET,
      budgets: [
        {
          ...WAITING,
          status: "REPLACED",
          approved_by_name: "Kompheak",
          approved_at: "2026-11-03T02:00:00+00:00",
          decision_note: "Repairs look low",
        },
      ],
    };
    const api = fakeApi({ read: vi.fn(() => Promise.resolve(back)) });
    show(api, ACCOUNTANT, ACCOUNTANT_ID);
    expect(
      await screen.findByText("Sent back by Kompheak: Repairs look low"),
    ).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "6050 · Repairs and maintenance" }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Same amount every month"), {
      target: { value: "300" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Fill all months" }),
    );
    expect(within(dialog).getByLabelText("December")).toHaveValue("300");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Budget amounts saved."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send to the Owner" }));
    expect(
      await screen.findByText("Budget 2027 sent to the Owner."),
    ).toBeInTheDocument();
    const sent = vi.mocked(api.send).mock.calls[0];
    expect(sent?.[1]).toBe(2027);
    expect(sent?.[2]).toHaveLength(24);
    expect(sent?.[2]).toContainEqual({
      account_code: "6050",
      month_no: 12,
      amount_cents: 30_000,
    });
    expect(sent?.[3]).toBeNull();
  });

  it("TEST-FE-1207 asks the Owner for a note on their own budget and shows it approved and locked", async () => {
    const empty: BudgetSheet = {
      ...SHEET,
      budgets: [],
      earlier_lines: RENT,
    };
    const approved: BudgetSheet = {
      ...SHEET,
      budgets: [
        {
          ...WAITING,
          status: "APPROVED",
          created_by: OWNER_ID,
          created_by_name: "Kompheak",
          approved_by_name: "Kompheak",
          approved_at: "2026-11-04T02:00:00+00:00",
          own_note: "My plan",
          lines: RENT,
        },
      ],
    };
    const read = vi
      .fn<BudgetApi["read"]>()
      .mockResolvedValueOnce(empty)
      .mockResolvedValue(approved);
    const api = fakeApi({ read });
    show(api, OWNER, OWNER_ID);
    fireEvent.click(
      await screen.findByRole("button", { name: "Send to the Owner" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Your own budget is approved at once. Add a note for the record.",
    );
    fireEvent.change(within(dialog).getByLabelText(/^Note/), {
      target: { value: "My plan" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Send to the Owner" }),
    );
    expect(
      await screen.findByText("Budget 2027 approved."),
    ).toBeInTheDocument();
    expect(api.send).toHaveBeenCalledWith("prop-1", 2027, RENT, "My plan");
    expect(
      await screen.findByText("An approved budget is locked."),
    ).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Send to the Owner" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1208 switches the year", async () => {
    const api = fakeApi();
    show(api, ACCOUNTANT, ACCOUNTANT_ID);
    fireEvent.click(await screen.findByRole("button", { name: "2026" }));
    expect(api.read).toHaveBeenLastCalledWith("prop-1", 2026);
  });
});
