import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthEndPage } from "./MonthEndPage";
import type { MonthEnd, MonthEndApi } from "./monthEndClient";

afterEach(() => {
  cleanup();
});

const OCTOBER = {
  id: "p-10",
  starts_on: "2026-10-01",
  ends_on: "2026-10-31",
  status: "OPEN",
  fiscal_year: 2026,
  closed_by_name: null,
  closed_at: null,
};

const DATA: MonthEnd = {
  today: "2026-11-03",
  months: [
    {
      id: "p-11",
      starts_on: "2026-11-01",
      ends_on: "2026-11-30",
      status: "OPEN",
      fiscal_year: 2026,
      closed_by_name: null,
      closed_at: null,
    },
    OCTOBER,
    {
      id: "p-09",
      starts_on: "2026-09-01",
      ends_on: "2026-09-30",
      status: "CLOSED",
      fiscal_year: 2026,
      closed_by_name: "Kompheak",
      closed_at: "2026-10-05T10:00:00+07:00",
    },
  ],
  years: [
    {
      id: "y-2026",
      fiscal_year: 2026,
      status: "OPEN",
      entry_number: null,
      profit_cents: null,
      december_closed: false,
    },
    {
      id: "y-2025",
      fiscal_year: 2025,
      status: "OPEN",
      entry_number: null,
      profit_cents: null,
      december_closed: true,
    },
  ],
  month: OCTOBER,
  checks: [
    { code: "BOOKS_CHECK", ok: true, open_items: 0 },
    { code: "NOTHING_WAITING", ok: false, open_items: 2 },
    { code: "NO_LATE_ADVANCE", ok: true, open_items: 0 },
    { code: "BANK_MATCHED", ok: false, open_items: 1 },
    { code: "CASH_COUNTED", ok: true, open_items: 0 },
    { code: "DEPRECIATION_DONE", ok: true, open_items: 0 },
    { code: "RIEL_VALUED", ok: true, open_items: 0 },
    { code: "PAYROLL_APPROVED", ok: true, open_items: 0 },
  ],
  depreciation_entry: "JE260564",
  riel: { entry_number: null },
  riel_accounts: [],
};

const GREEN: MonthEnd = {
  ...DATA,
  checks: DATA.checks.map((check) => ({ ...check, ok: true, open_items: 0 })),
};

function fakeApi(extra: Partial<MonthEndApi> = {}): MonthEndApi {
  return {
    read: vi.fn(() => Promise.resolve(DATA)),
    closeMonth: vi.fn(() => Promise.resolve(true)),
    closeYear: vi.fn(() => Promise.resolve()),
    ...extra,
  };
}

function show(
  api: MonthEndApi,
  capabilities: ReadonlySet<string> | null = null,
) {
  render(
    <MonthEndPage
      active
      api={api}
      capabilities={capabilities}
      language="en"
      propertyId="prop-1"
    />,
  );
}

describe("Month-end close", () => {
  it("TEST-FE-1195 shows each check of the month to close and keeps Close off while one is red", async () => {
    show(fakeApi());
    expect(
      await screen.findByRole("heading", { name: "Close October 2026" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 to fix")).toBeInTheDocument();
    expect(
      screen.getByText(
        "2 Expense requests or adjusting entries dated in this month are still pending approval.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reconcile the bank account to the ABA statement for 31/10/2026.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "JE260564" })).toBeInTheDocument();
    expect(
      screen.getByText("No change: the riel value is the same."),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open" })).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Close October 2026" }),
    ).toBeDisabled();
    expect(screen.getByText("Fix the red lines first.")).toBeInTheDocument();
    expect(screen.getByText("To close now")).toBeInTheDocument();
    expect(screen.getByText(/^Closed by Kompheak/)).toBeInTheDocument();
  });

  it("TEST-FE-1700 shows each riel account's month-end value with the rate and the gain or loss", async () => {
    show(
      fakeApi({
        read: vi.fn(() =>
          Promise.resolve({
            ...DATA,
            riel_accounts: [
              {
                code: "1021",
                name_en: "ABA Bank · KHR account",
                name_km: null,
                cash_kind: "BANK_KHR",
                riel_held: 367_470,
                khr_per_usd: 4_100,
                before_cents: 9_000,
                after_cents: 8_963,
                gain_cents: -37,
                entry_number: "JE270031",
              },
            ],
          }),
        ),
      }),
    );
    const box = await screen.findByRole("region", {
      name: /Riel at month end/,
    });
    expect(box).toHaveTextContent("1021 · ABA Bank · KHR account");
    expect(within(box).getByText("367,470 ៛")).toBeInTheDocument();
    expect(within(box).getByText("4,100")).toBeInTheDocument();
    expect(within(box).getByText("$90.00")).toBeInTheDocument();
    expect(within(box).getByText("$89.63")).toBeInTheDocument();
    expect(within(box).getByText("-$0.37")).toBeInTheDocument();
    expect(
      within(box).getByRole("link", { name: "JE270031" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1196 closes the month when every line is green", async () => {
    const api = fakeApi({ read: vi.fn(() => Promise.resolve(GREEN)) });
    show(api);
    expect(await screen.findByText("Ready to close")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close October 2026" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Every check is green. After closing, nothing can be dated in October 2026.",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close month" }),
    );
    expect(await screen.findByText("October 2026 closed.")).toBeInTheDocument();
    expect(api.closeMonth).toHaveBeenCalledWith("prop-1", "p-10");
  });

  it("TEST-FE-1197 closes a year after December and says the entry", async () => {
    const closed: MonthEnd = {
      ...DATA,
      years: DATA.years.map((item) =>
        item.id === "y-2025"
          ? {
              ...item,
              status: "CLOSED",
              entry_number: "JE251299",
              profit_cents: 1_234_500,
            }
          : item,
      ),
    };
    const read = vi
      .fn<MonthEndApi["read"]>()
      .mockResolvedValueOnce(DATA)
      .mockResolvedValue(closed);
    const api = fakeApi({ read });
    show(api);
    expect(
      await screen.findByText(
        "You can close 2026 after December 2026 is closed.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close year" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close year" }));
    expect(
      await screen.findByText("Year 2025 closed. Entry JE251299."),
    ).toBeInTheDocument();
    expect(api.closeYear).toHaveBeenCalledWith("prop-1", "y-2025");
    await waitFor(() => {
      expect(screen.getByText("$12,345.00")).toBeInTheDocument();
    });
  });

  it("TEST-FE-1198 tells a reader without the close right that only the Owner closes", async () => {
    show(
      fakeApi({ read: vi.fn(() => Promise.resolve(GREEN)) }),
      new Set(["ledger.read"]),
    );
    expect(
      await screen.findByText("Only the Owner closes a month."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Close October 2026" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Close year" }),
    ).not.toBeInTheDocument();
  });
});
